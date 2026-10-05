# Security policy

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private vulnerability reporting on this repository
(*Security → Report a vulnerability*), or email [lets@eait.fit](mailto:lets@eait.fit) with
"security" in the subject.

Include what you found, where (file, route, or version), how to reproduce it, and what you think
the impact is. You will get an acknowledgement within 3 working days and a decision on severity
and a fix timeline within 10. Please keep the report private until a fix has shipped; you will be
credited in the fix unless you ask not to be.

## What is in scope

This repository: the API, the fetchers, the job worker and the self-hosting stack under `deploy/`.
A finding against the hosted service at `food-api.eait.fit` is welcome too, but stop at proof and do
not degrade the service for others.

Out of scope: the upstream data sources (USDA FoodData Central, Open Food Facts), which have their
own programmes.

## Supported versions

`main` and the latest tagged release.
