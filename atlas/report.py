"""Local reports with escaped content and no remote assets or scripts."""

from html import escape


def render_html(results):
    cards = []
    for result in results:
        reasons = result["gates"] + result["reasons"]
        items = (
            "".join(f"<li>{escape(str(reason))}</li>" for reason in reasons)
            or "<li>All declared research checks passed. Execution remains disabled.</li>"
        )
        checks = "".join(
            f'<tr><td>{escape(str(c["id"]))}</td><td>{escape(c["name"])}</td><td>{"PASS" if c["pass_"] else "FAIL"}</td></tr>'
            for c in result["checks"]
        )
        cards.append(
            f'<article><p class="label">{escape(result["status"])} · {escape(result["evidence_status"])}</p><h2>{escape(result["name"])}</h2><p>{escape(result["ticker"])} · observed {escape(result["price_date"])} · evaluated {escape(result["as_of"])}</p><ul>{items}</ul><details><summary>Inspect every rule</summary><table><tr><th>ID</th><th>Research check</th><th>Result</th></tr>{checks}</table></details><p class="hash">Input SHA-256: {escape(result["input_sha256"])}</p></article>'
        )
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'"><title>Bottleneck Atlas · Research evidence</title><style>
body{background:#101719;color:#e8efeb;font:16px/1.65 system-ui,sans-serif;max-width:980px;margin:auto;padding:40px 24px}h1{font-size:clamp(32px,6vw,56px);line-height:1.1;letter-spacing:-2px}h2{font-size:24px}p{color:#bdcec5}.label{color:#b6e778;font:700 12px/1.6 monospace;letter-spacing:1px}article{border:1px solid #3e544b;border-radius:12px;padding:24px;margin:24px 0;background:#172320}table{border-collapse:collapse;width:100%;text-align:left}th,td{padding:10px;border-bottom:1px solid #3e544b}.hash{font:11px monospace;overflow-wrap:anywhere}summary{cursor:pointer;color:#b6e778}footer{border-top:1px solid #3e544b;padding-top:24px;color:#bdcec5}</style><body><p class="label">BOTTLENECK ATLAS / LOCAL RESEARCH</p><h1>Show the evidence.<br>Expose the gaps.</h1><p>Deterministic equity research checks for AI infrastructure, minerals and power.</p><p><strong>Research only. Synthetic examples are not market observations. No orders, email or remote writes.</strong></p>"""
        + "".join(cards)
        + "<footer>Scores are heuristic. No validated investment performance is claimed. This output does not constitute financial advice. Grok Bot is a third-party product; no affiliation is implied.</footer></body></html>\n"
    )
