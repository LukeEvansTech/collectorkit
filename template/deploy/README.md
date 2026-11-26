# Cluster manifests

The worked example for the home cluster, kept as text here because the cluster repository is
where these files are validated. Create each file below under
`kubernetes/apps/custom/<app>/`, register the app in the namespace kustomization, add a row for
the model key to the cluster's model-stack documentation, and replace every `myapp`.

- The route sits behind the cluster's sign-in component; the `public` route opens `/img` only,
  so a mail client can load photos.
- `prometheusrule.yaml` carries the two alerts every collector has. Set the age threshold from
  the schedule.
- The 1Password item `myapp` needs `PUSHOVER_USER_KEY`, `PUSHOVER_APP_TOKEN` and
  `MYAPP_MAIL_TO`.

## `kubernetes/apps/custom/<app>/ks.yaml`

```yaml
---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app myapp
  namespace: &namespace custom
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  components:
    - ../../../../components/homepage
    - ../../../../components/pocket-id
  dependsOn:
    - name: litellm
      namespace: ai
    - name: onepassword-connect
      namespace: external-secrets
  interval: 1h
  path: ./kubernetes/apps/custom/myapp/app
  postBuild:
    substitute:
      APP: *app
      VOLSYNC_CAPACITY: 5Gi
      VOLSYNC_PUID: "65532"
      VOLSYNC_PGID: "65532"
      HOMEPAGE_NAME: Myapp
      HOMEPAGE_ICON: /icons/dracula/myapp.svg
      HOMEPAGE_DESCRIPTION: What it collects
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: *namespace
  timeout: 5m
  wait: false
```

## `app/kustomization.yaml`

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./externalsecret.yaml
  - ./pvc.yaml
  - ./ocirepository.yaml
  - ./helmrelease.yaml
  - ./prometheusrule.yaml
  # Backups only, not the full volsync component: its pvc.yaml would provision the PVC from a
  # ReplicationDestination.
  - ../../../../components/volsync/nfs
  - ../../../../components/volsync/remote
```

## `app/ocirepository.yaml`

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: myapp
spec:
  interval: 1h
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: 5.3.0
  url: oci://ghcr.io/bjw-s-labs/helm/app-template
```

## `app/pvc.yaml`

```yaml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: myapp
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
  storageClassName: ceph-block
```

## `app/helmrelease.yaml`

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: myapp
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: myapp
  values:
    controllers:
      myapp:
        annotations:
          reloader.stakater.com/auto: "true"
        # Recreate avoids a multi-attach deadlock on this RWO ceph-block PVC.
        strategy: Recreate
        containers:
          app:
            image:
              repository: ghcr.io/lukeevanstech/myapp
              tag: 0.1.0 # Renovate appends the digest
            env:
              TZ: ${TIMEZONE}
              MYAPP_DATA: /data
              MYAPP_PUBLIC_URL: https://myapp.${SECRET_DOMAIN}
              # One sweep a day; the mail goes out when it found something new.
              MYAPP_SCHEDULE: "0 7 * * *"
              MYAPP_TZ: Europe/London
              MYAPP_LLM_URL: http://litellm.ai.svc.cluster.local:4000/v1
              MYAPP_LLM_MODEL: claude
              # The mail goes through the cluster relay; the LAN name matches its certificate.
              # The recipient comes from the secret (MYAPP_MAIL_TO).
              MYAPP_SMTP_HOST: smtp.${SECRET_DOMAIN}
              MYAPP_MAIL_FROM: noreply@${SECRET_DOMAIN}
            envFrom:
              - secretRef:
                  name: myapp-secret
            probes:
              liveness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /health
                    port: &port 8080
                  initialDelaySeconds: 10
                  periodSeconds: 30
                  timeoutSeconds: 5
                  failureThreshold: 3
              readiness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /health
                    port: *port
                  initialDelaySeconds: 5
                  periodSeconds: 10
                  timeoutSeconds: 10
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities:
                drop:
                  - ALL
            # Raise the limit to 2Gi for an app that runs a browser inside the pod.
            resources:
              requests:
                cpu: 20m
                memory: 128Mi
              limits:
                memory: 512Mi
    defaultPodOptions:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
        runAsGroup: 65532
        fsGroup: 65532
        fsGroupChangePolicy: OnRootMismatch
        seccompProfile:
          type: RuntimeDefault
    service:
      app:
        # The route only proves the sign-in redirect (pocket-id component); this checks the app.
        annotations:
          gatus.home-operations.com/enabled: "true"
          gatus.home-operations.com/endpoint: |-
            name: myapp-service
            group: internal
            url: http://myapp.custom.svc.cluster.local:8080/health
            conditions: ["[STATUS] == 200"]
        controller: myapp
        ports:
          http:
            port: *port
    # /metrics carries the last delivering sweep; /health cannot see that.
    serviceMonitor:
      app:
        serviceName: "{{ .Release.Name }}"
        endpoints:
          - port: http
            scheme: http
            path: /metrics
            interval: 1m
            scrapeTimeout: 10s
    route:
      app:
        # A second route would otherwise rename this one myapp-app; the pocket-id component targets .
        forceRename: "{{ .Release.Name }}"
        hostnames:
          - "myapp.${SECRET_DOMAIN}"
        parentRefs:
          - name: envoy-internal
            namespace: network
      # Outside the Pocket ID sign-in: the email loads photos from here, and a mail
      # client has no session cookie.
      public:
        annotations:
          gatus.home-operations.com/enabled: "false"
        hostnames:
          - "myapp.${SECRET_DOMAIN}"
        parentRefs:
          - name: envoy-internal
            namespace: network
        rules:
          - matches:
              - path:
                  type: PathPrefix
                  value: /img
            backendRefs:
              - identifier: app
                port: *port
    persistence:
      data:
        existingClaim: myapp
        globalMounts:
          - path: /data
      tmp:
        type: emptyDir
        globalMounts:
          - path: /tmp
```

## `app/externalsecret.yaml`

```yaml
---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/external-secrets.io/externalsecret_v1.json
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: myapp
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: myapp-secret
    template:
      engineVersion: v2
      data:
        # The app's own Pushover application.
        APPRISE_URLS: "pover://{{ .PUSHOVER_USER_KEY }}@{{ .PUSHOVER_APP_TOKEN }}"
        # A scoped model key (virtualkey.yaml), mirrored to the litellm item by its PushSecret.
        MYAPP_LLM_KEY: "{{ .LITELLM_MYAPP_API_KEY }}"
        # The address stays in the vault.
        MYAPP_MAIL_TO: "{{ .MYAPP_MAIL_TO }}"
  dataFrom:
    - extract:
        key: myapp
    - extract:
        key: litellm
```

## `app/prometheusrule.yaml`

```yaml
---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/monitoring.coreos.com/prometheusrule_v1.json
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: myapp
  namespace: custom
spec:
  groups:
    - name: myapp
      rules:
        # Alerts on the outcome, not process health: a sweep counts only when it read listings
        # and its mail did not fail. Sweeps run daily, so 36h is one missed sweep plus slack;
        # the 1h wait covers a fresh install, when the metric is 0 until the first sweep ends.
        - alert: MyappNotDelivering
          annotations:
            summary: >-
              myapp has not completed a delivering sweep in over 36h, so its listings and
              its email are stale.
            description: >-
              The last delivering myapp sweep finished {{ $value | humanizeDuration }} ago.
              Check its home page for per-source coverage, or kubectl -n custom logs
              deploy/myapp.
          expr: |-
            time() - myapp_last_success_timestamp_seconds > 129600
          for: 1h
          labels:
            severity: warning
        - alert: MyappMetricsMissing
          annotations:
            summary: >-
              myapp /metrics has not been scraped for 30m, so its sweeps are unmonitored.
          expr: |-
            absent(myapp_last_success_timestamp_seconds)
          for: 30m
          labels:
            severity: warning
```

## `kubernetes/apps/ai/litellm/app/virtualkeys/<app>.yaml`

```yaml
---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/litellm.home-operations.com/litellmvirtualkey_v1alpha1.json
apiVersion: litellm.home-operations.com/v1alpha1
kind: LiteLLMVirtualKey
metadata:
  name: myapp
  namespace: ai
spec:
  # Cross-namespace key: PushSecret mirrors it to the litellm 1Password item
  # (docs/docs/architecture/ai-llm-stack.md In-cluster consumers).
  proxyRef: litellm
  keyAlias: myapp
  secretName: litellm-key-myapp
  secretKey: api-key
  # Say what the app asks and how often, and add a maxBudget.
  models:
    - claude
---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/external-secrets.io/pushsecret_v1alpha1.json
apiVersion: external-secrets.io/v1alpha1
kind: PushSecret
metadata:
  name: myapp
  namespace: ai
spec:
  refreshInterval: 1h
  secretStoreRefs:
    - name: onepassword-connect
      kind: ClusterSecretStore
  selector:
    secret:
      name: litellm-key-myapp
  updatePolicy: Replace
  data:
    - match:
        secretKey: api-key
        remoteRef:
          remoteKey: litellm
          property: LITELLM_MYAPP_API_KEY
```
