# render-deployment-page.jq — page logic for render-deployment-page.sh (TKT-DDP-02)
#
# Renders a CDK outputs object into the deterministic, scannable Markdown page.
# All page logic lives here (not text-munged in shell) so ordering and slot
# resolution are done over the parsed JSON, keeping output byte-stable across
# runs. Invoked as `jq -r -f render-deployment-page.jq --arg env … --arg ts …
# --arg ver … --arg maint … --arg degraded … outputs.json`.
#
# Slot resolution: each "slot" (CloudFront URL, API base, …) carries an ordered
# list of candidates. A candidate is either exact ({t:"x", n:KEY}, case-
# insensitive whole-key match) or fuzzy ({t:"f", terms:[…]}, case-insensitive
# substring-of-key for every term). `pick` returns the first candidate (highest
# priority) that matches anything; among that candidate's matches it takes the
# lexicographically smallest `<stack>.<key>`. Exact candidates are listed before
# fuzzy ones, so an exact key always wins over a fuzzy hit.

def lc: ascii_downcase;
# Render a URL-looking value as a Markdown link, anything else verbatim.
def fmt($v):
  if (($v|type)=="string")
     and (($v|startswith("http://")) or ($v|startswith("https://")))
  then "[\($v)](\($v))"
  else ($v|tostring)
  end;
# Quick-access / table cell: missing → n/a, else formatted value.
def slot($v): if $v == null then "n/a" else fmt($v) end;
# Highest-priority candidate match, lexicographically smallest sk on a tie.
def pick($ents; $cands):
  ( first(
      $cands[] as $c
      | ( if $c.t == "x"
          then [ $ents[] | select((.key|lc) == ($c.n|lc)) ]
          else [ $ents[]
                 | . as $e
                 | select($c.terms | all(. as $t | ($e.key|lc|contains($t)))) ]
          end )
      | select(length > 0)
      | (sort_by(.sk) | .[0])
    ) ) // null;

[ to_entries[]
  | .key as $stack
  | (.value // {})
  | to_entries[]
  | { stack: $stack, key: .key, value: .value, sk: "\($stack).\(.key)" }
] as $ents

| pick($ents; [ {t:"x",n:"CloudFrontDistributionUrl"},
                {t:"x",n:"CloudFrontUrl"},
                {t:"x",n:"FrontendUrl"},
                {t:"f",terms:["cloudfront","url"]} ]).value          as $cf
| pick($ents; [ {t:"x",n:"ApiUrl"},
                {t:"x",n:"ApiGatewayApiGatewayUrl"},
                {t:"x",n:"ApiGatewayApiEndpoint"},
                {t:"f",terms:["api","url"]} ]).value                 as $api
| pick($ents; [ {t:"x",n:"ApiHealthEndpoint"},
                {t:"x",n:"ApiGatewayHealthEndpoint"},
                {t:"f",terms:["health","endpoint"]} ]).value         as $health
| pick($ents; [ {t:"x",n:"ApiChatEndpoint"},
                {t:"x",n:"ApiGatewayChatEndpoint"},
                {t:"f",terms:["chat","endpoint"]} ]).value           as $chat
| pick($ents; [ {t:"x",n:"CloudFrontDistributionId"},
                {t:"f",terms:["cloudfront","distribution","id"]} ]).value as $cfid
| pick($ents; [ {t:"x",n:"ApiGatewayId"},
                {t:"f",terms:["apigateway","id"]} ]).value           as $apiid
| pick($ents; [ {t:"x",n:"GuardrailGuardrailId"},
                {t:"x",n:"GuardrailId"},
                {t:"f",terms:["guardrail","id"]} ]).value            as $gid
| pick($ents; [ {t:"x",n:"GuardrailGuardrailVersionOutput"},
                {t:"x",n:"GuardrailVersion"},
                {t:"f",terms:["guardrail","version"]} ]).value       as $gver

# Maintenance marker (TKT-MM-03): suffix the version and emit a banner when
# the environment's version.yaml sets `maintenance: true`.
| (if $maint == "true" then "\($ver)-maintenance" else $ver end) as $verstr

# Degraded-rollback marker (#628): any non-empty, non-"false" $degraded value
# emits a banner — presence wins, the value is never required to parse. When
# it happens to be the marker JSON (schema_version/release_id/opened_at), the
# banner is enriched with the release id and open timestamp; any other
# non-empty value still renders a (less detailed) banner rather than none, so
# the page can never silently fail to show a real degraded window.
| ($degraded != "" and $degraded != "false") as $isDegraded
| (if $isDegraded then ($degraded | try fromjson catch null) else null end) as $degradedInfo
| (if $isDegraded then
     "> 🔴 **RETRIEVAL ROLLBACK DEGRADED** — fast #493 rollback unavailable"
     + (if ($degradedInfo | type) == "object" and ($degradedInfo.release_id // null) != null
        then " — release \($degradedInfo.release_id)"
             + (if ($degradedInfo.opened_at // null) != null
                then ", since \($degradedInfo.opened_at)" else "" end)
        else "" end)
   else null end) as $degradedBanner

| ( [ "# Deployment outputs — \($env)",
      "",
      "_Last updated: \($ts)_" ]
    # Banner directly under the header so maintenance is unmissable.
    # TODO (Iteration 2): render reason/owner/expected_off next to the banner.
    + (if $maint == "true"
       then ["", "> ⚠️ **MAINTENANCE MODE ACTIVE**"]
       else [] end)
    + (if $isDegraded then ["", $degradedBanner] else [] end)
    + [ "",
      "## Quick access",
      "- Frontend (CloudFront): \(slot($cf))",
      "- Guardrails: ID=\(slot($gid)) · Version=\(slot($gver))",
      "- Version: \($verstr)" ]
    + (if $data_ver != "" then ["- Data version: \($data_ver)"] else [] end)
    + (if $etl_ver != "" then ["- ETL version: \($etl_ver)"] else [] end)
    + [ "- API base: \(slot($api))",
      "- API health: \(slot($health))",
      "- API chat: \(slot($chat))",
      "",
      "## Key endpoints",
      "| Label | Value |",
      "|---|---|",
      "| CloudFront URL | \(slot($cf)) |",
      "| API Base URL | \(slot($api)) |",
      "| API Health Endpoint | \(slot($health)) |",
      "| API Chat Endpoint | \(slot($chat)) |",
      "",
      "## Important IDs",
      "| Label | Value |",
      "|---|---|",
      "| CloudFront Distribution ID | \(slot($cfid)) |",
      "| API Gateway ID | \(slot($apiid)) |",
      "" ]
    # Retrieval promotion evidence (#643 D11): rendered only when $evidence is a
    # non-empty JSON object. QA does not pass it, so QA's page stays byte-
    # identical; preprod passes the candidate manifest + attestation so the audit
    # page exposes release/artifact identity, both image digests, the slot flip,
    # ingestion state, and the implementation fingerprint. Every field degrades
    # to n/a individually — a missing field must never blank the section.
    + ( ($evidence | if . == "" then null else (try fromjson catch null) end)
        | if (type == "object") then
            [ "## Retrieval promotion evidence",
              "| Field | Value |",
              "|---|---|",
              "| Release ID | \(slot(.release_id)) |",
              "| Retrieval artifact ID | \(slot(.retrieval_artifact_id)) |",
              "| Chatbot image digest | \(slot(.chatbot_image_digest)) |",
              "| ETL image digest | \(slot(.etl_image_digest)) |",
              "| Active slot before | \(slot(.active_slot_before)) |",
              "| Active slot after (now live) | \(slot(.active_slot_after)) |",
              "| Ingestion state | \(slot(.ingestion_state)) |",
              "| Implementation fingerprint | \(slot(.implementation_fingerprint)) |",
              "" ]
          else [] end )
    + [ "## All outputs",
      "| Stack | Key | Value |",
      "|---|---|---|" ]
    + ( $ents
        | sort_by([.stack, .key])
        | map("| \(.stack) | \(.key) | \(fmt(.value)) |") )
  )
| .[]
