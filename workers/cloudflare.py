"""Private site on Cloudflare: a Pages project for the comps page, behind Cloudflare Access (only the owner's email).

    python3 -m workers.cloudflare setup      # check the token, create the Pages project and the Access app (idempotent)
    python3 -m workers.cloudflare url        # print the site's pages.dev host

Reads CF_TOKEN (the owner's Cloudflare API token, GitHub secret) and ACCESS_EMAIL (ENTRANT_EMAIL) from the environment;
prints only what was done or what failed, never a secret. The deploy itself is `wrangler pages deploy` in site.yml.
Token permissions needed (account): Cloudflare Pages Edit, Access: Apps and Policies Edit, Account Settings Read.
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
PROJECT = os.environ.get("CF_PROJECT", "comp-quest")


def call(method, path, body=None, token=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token or os.environ['CF_TOKEN']}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read())
        except ValueError:
            return {"success": False, "errors": [{"code": exc.code, "message": exc.reason}]}


def errors(r):
    return "; ".join(f"{e.get('code')}: {e.get('message')}" for e in r.get("errors") or []) or "unknown error"


def account():
    r = call("GET", "/accounts?per_page=5")
    if not r.get("success") or not r.get("result"):
        sys.exit(f"cloudflare: cannot list accounts ({errors(r)}). The token needs Account Settings: Read.")
    return r["result"][0]["id"]


def project(acc):
    r = call("GET", f"/accounts/{acc}/pages/projects/{PROJECT}")
    if r.get("success"):
        return r["result"]["subdomain"]
    r = call("POST", f"/accounts/{acc}/pages/projects", {"name": PROJECT, "production_branch": "main"})
    if not r.get("success"):
        sys.exit(f"cloudflare: cannot create the Pages project ({errors(r)}). The token needs Cloudflare Pages: Edit.")
    print(f"cloudflare: created Pages project {PROJECT}")
    return r["result"]["subdomain"]


def access(acc, host, email):
    """A self-hosted Access app on the pages.dev host that lets in only the owner's email (one-time PIN by email)."""
    org = call("GET", f"/accounts/{acc}/access/organizations")
    if not org.get("success") or not org.get("result"):
        r = call("POST", f"/accounts/{acc}/access/organizations",
                 {"name": "Comp Quest", "auth_domain": f"{PROJECT}-{acc[:6]}.cloudflareaccess.com"})
        if not r.get("success"):
            return f"Zero Trust is not set up on the account yet ({errors(r)})"
        print("cloudflare: set up Zero Trust (team domain)")
    apps = call("GET", f"/accounts/{acc}/access/apps")
    if not apps.get("success"):
        return f"cannot read Access apps ({errors(apps)}); the token needs Access: Apps and Policies Edit"
    app = next((a for a in apps["result"] if a.get("domain") in (host, f"*.{host}")), None)
    policy = {"name": "Owner only", "decision": "allow", "include": [{"email": {"email": email}}]}
    if app is None:
        r = call("POST", f"/accounts/{acc}/access/apps",
                 {"name": "Comp Quest", "type": "self_hosted", "domain": host, "session_duration": "720h",
                  "app_launcher_visible": False, "policies": [policy]})
        if not r.get("success"):
            return f"cannot create the Access app ({errors(r)})"
        print(f"cloudflare: Access app created; only the owner's email can open {host}")
        return None
    print(f"cloudflare: Access app already protects {host}")
    return None


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not os.environ.get("CF_TOKEN"):
        sys.exit("cloudflare: no token in the environment (GitHub secret CLOUDFLARE_API).")
    v = call("GET", "/user/tokens/verify")
    if not v.get("success"):
        sys.exit(f"cloudflare: token rejected ({errors(v)})")
    acc = account()
    host = project(acc)
    if args[:1] == ["url"]:
        print(host)
        return
    print(f"cloudflare: token ok; Pages project {PROJECT} at https://{host}")
    email = os.environ.get("ACCESS_EMAIL")
    problem = access(acc, host, email) if email else "no ACCESS_EMAIL set"
    if problem:
        print(f"cloudflare: site NOT private yet: {problem}")
        sys.exit(2)


if __name__ == "__main__":
    main()
