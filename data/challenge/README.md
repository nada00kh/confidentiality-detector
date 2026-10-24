# Challenge set v1 — independently written evaluation cases

`challenge_v1.txt` holds hand-written cases that imitate what employees actually paste into an
LLM prompt: chat requests, e-mails, support tickets, code, configs, logs, forms, and long notes.
It is **evaluation-only**. Nothing from it may be used for training, threshold tuning, or model
selection. The file was written and hashed before any model was scored on it; the hash is in
`challenge_v1.sha256`. If you change a case, create `challenge_v2` rather than editing v1.

All values are fictional: phone numbers use the reserved 555-01xx range, card numbers are public
test numbers, IBANs are published specimen IBANs, and every name, username and password is invented.

## Markup

```
@@ <case-id> | <tag>,<tag>,...
text with [[LABEL:value]] target spans, [[~TAG:value]] ignore spans and [[!TAG:value]] negatives
```

* `[[LABEL:value]]`: a gold target entity; LABEL is one of the 13 target labels.
* `[[~TAG:value]]`: ambiguous span. Predictions overlapping it are neither rewarded nor
  penalised, and a case whose only annotations are ignore spans is excluded from the
  document-level metrics.
* `[[!TAG:value]]`: an out-of-scope look-alike (PIN, IPv6, order number, version, public figure).
  Predictions on it count as false positives and are reported as hard-negative errors.
* A case with no `[[LABEL:...]]` span is an ALLOW case.

## Annotation guidelines

| Label | Annotate | Do not annotate |
|---|---|---|
| FIRSTNAME / LASTNAME | private individuals' given / family names, including lower-case and greetings; one span per name token | titles (Mr., Dr.), public figures, fictional characters, company names (mark `!PUBLICNAME`) |
| STREET | street name with its suffix ("Elm Street"); the house number is excluded, matching the training data convention | city, state, ZIP |
| USERNAME | login names and handles | the local part of an e-mail address (part of EMAIL) |
| PASSWORD | the secret value only | the word "password", placeholders such as `<password>` or `********` |
| EMAIL | full address | — |
| PHONENUMBER | full number including country code and punctuation | extensions written as words |
| SSN | the number | — |
| CREDITCARDNUMBER / CREDITCARDCVV / IBAN / ACCOUNTNUMBER | the value with its internal separators | order, invoice, ticket, tracking and routing numbers (mark `!` if they look similar) |
| IPV4 | any IPv4 host address, including private ranges | 127.0.0.1, 0.0.0.0 and netmasks (`~AMBIG`) |

API keys and access tokens are outside the 13-label scope (final decision, 2026-10-23: no secret-detection layer).
This file marks the one such value (`code-013`) `~SECRET`, i.e. ignored. Decision F (2026-10-23, after Round 2)
says an out-of-scope key predicted as PASSWORD must count as a false positive and, in a document without targets,
as a False BLOCK. The file stays frozen. The second overlay version `challenge_v1_overlay_final_policy_v2.json`
(name policy + decision F) produces `challenge_v1_final`, in which `code-013` is an ALLOW case with an `APIKEY`
look-alike. `challenge_v1_policy` (overlay version 1) is kept unchanged, as Round 2 evaluated it.

**Final person-name policy (2026-10-23).** Public figures are FIRSTNAME/LASTNAME targets. This file predates that
decision and annotates four cases (three with real public figures, one with fictional characters) as `!PUBLICNAME` negatives. The file stays frozen; the overlay
`challenge_v1_overlay_final_policy.json` produces the policy-consistent set `challenge_v1_policy`. Both are reported.
This set's failures were studied after round 1, so it is now a regression/debugging set, not an unbiased benchmark.
