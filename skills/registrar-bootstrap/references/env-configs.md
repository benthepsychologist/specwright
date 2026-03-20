# Environment Config Expectations

Use these checks after `registrar bootstrap --env ...`.

## dev

- Dev datasets exist
- Non-prod secrets exist
- Least-privilege dev IAM bindings exist

## stage

- Stage datasets and IAM bindings exist
- Stage secrets exist
- Labels/locations match platform policy

## prod

- Production IAM bindings exist and are restricted
- Production datasets and retention policy are configured
- Production secrets and key references are present
