# Cluster manifests

The worked example for the home cluster. Copy `ks.yaml` and `app/` to
`kubernetes/apps/custom/<app>/` and register the app in the namespace kustomization.
`virtualkey.yaml` goes to `kubernetes/apps/ai/litellm/app/virtualkeys/<app>.yaml`, with a row in
the cluster's model-stack documentation. Replace every `myapp`.

- The route sits behind the cluster's sign-in component; the `public` route opens `/img` only,
  so a mail client can load photos.
- `prometheusrule.yaml` carries the two alerts every collector has. Set the age threshold from
  the schedule.
- The 1Password item `myapp` needs `PUSHOVER_USER_KEY`, `PUSHOVER_APP_TOKEN` and
  `MYAPP_MAIL_TO`.
