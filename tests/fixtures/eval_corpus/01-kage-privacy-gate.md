## What it does
The privacy gate decides what may leave the machine before any cloud call.

## How it works
Three checks run in order: the local_only flag, the project rule, then a PII
scan across 29 patterns. If anything is withheld, the user is asked before dispatch.
