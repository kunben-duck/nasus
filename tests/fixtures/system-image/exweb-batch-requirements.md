# US-EXWEB-BATCH Multi-call browser protocol fixture
Description: Synthetic Nasus verification requirements for a pinned exweb checkout. These are not approved exweb product requirements or proof of runtime behavior.
## Acceptance criteria
AC-EXWEB-B1: Preserve a valid chat request and an independently confirmed observable response header in the proposed case.
AC-EXWEB-B2: Preserve an empty-input boundary request and an independently confirmed response observation without inferring current runtime behavior.
AC-EXWEB-B3: Preserve a Unicode request and its independently confirmed observation without assuming static code proves encoding behavior.
## Business rules
BR-EXWEB-B1: Global fixture constraint: use isolated synthetic data, do not run the target repository or call external providers, and do not expose credentials.
