# Firebase push delivery

Push notifications are stored in the database before delivery. The API does not
contact Firebase during a request. A scheduled Cloud Run Job runs the pending
delivery command, retries temporary failures with backoff, and records failures.
Notifications remain visible in the app if a push cannot be delivered.

Production uses project `pilah-app`, region `asia-southeast2`, and Cloud SQL
instance `pilah-app:asia-southeast2:pilah-postgres`. The existing API runtime
identity is `pilah-be-runtime@pilah-app.iam.gserviceaccount.com`. As inspected
on 2026-11-09, its project-level role was Cloud SQL Client; confirm its effective
permissions before deploying. The worker needs `cloudmessaging.messages.create`,
Cloud SQL Client, and access to its database and Django secrets. Prefer a custom
role containing only the messaging permission over the broader Firebase Cloud
Messaging Admin role. Use application-default credentials, not a key file.

Provisioning requires a release image containing this change, a worker service
account, a scheduler service account with Cloud Run Invoker on the job, and
Secret Manager versions holding the same `DB_NAME`, `DB_USER`, `DB_PASSWORD`,
and `DJANGO_SECRET_KEY` as the API. Do not put secret values in shell arguments
or commit them. Grant the worker Secret Manager access to those secrets. The
API's current deployment supplies some values as literal environment variables;
make corresponding secrets available before creating the job.

Once those prerequisites are ready, set `IMAGE` to the immutable release image,
`WORKER_SA` to the worker service account, and `SCHEDULER_SA` to the scheduler
service account. Replace the four example secret names below with the actual
Secret Manager names. Review these commands before running them:

```sh
gcloud run jobs deploy pilah-push-delivery \
  --project=pilah-app --region=asia-southeast2 --image="$IMAGE" \
  --service-account="$WORKER_SA" --command=/app/docker/push-entrypoint.sh \
  --set-cloudsql-instances=pilah-app:asia-southeast2:pilah-postgres \
  --set-env-vars='DJANGO_DEBUG=false,FIREBASE_PROJECT_ID=pilah-app,DB_ENGINE=django.db.backends.postgresql,DB_HOST=/cloudsql/pilah-app:asia-southeast2:pilah-postgres,DB_PORT=5432' \
  --set-secrets='DB_NAME=PILAH_DB_NAME:latest,DB_USER=PILAH_DB_USER:latest,DB_PASSWORD=PILAH_DB_PASSWORD:latest,DJANGO_SECRET_KEY=PILAH_DJANGO_SECRET_KEY:latest' \
  --tasks=1 --task-timeout=10m

gcloud scheduler jobs create http pilah-push-delivery \
  --project=pilah-app --location=asia-southeast2 --schedule='* * * * *' \
  --http-method=POST \
  --uri='https://run.googleapis.com/v2/projects/pilah-app/locations/asia-southeast2/jobs/pilah-push-delivery:run' \
  --oauth-service-account-email="$SCHEDULER_SA" \
  --oauth-token-scope='https://www.googleapis.com/auth/cloud-platform'
```

Enable the Cloud Run Jobs and Cloud Scheduler APIs as needed, and confirm the
Cloud Scheduler service agent can mint tokens for the scheduler identity. The
job entrypoint skips web startup, migrations, and static collection. Row locks
prevent overlapping workers from processing the same pending delivery. Configure
alerts for failed job executions and failed delivery rows. Run an initial job
against demo accounts and a real device, then verify delivery, retry, and invalid
token cleanup before relying on it. Deploying the API alone does not start the
worker.

The `deliver_push` command also queues one reminder for each eligible recipient
when a published schedule is two hours from starting. Cloud Scheduler runs it
every minute; schedules published after that reminder time are skipped instead
of receiving a misleading late reminder.

The worker reuses one authenticated FCM session for each command run. It still
holds the delivery row lock while waiting for FCM; moving the request outside the
transaction needs a claim lease and stale-claim recovery to avoid duplicate sends.
Notification history has no retention or pagination policy yet, so delivery rows
and the inbox remain unbounded until those policies are agreed with the client.
