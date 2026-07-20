# systemd resource drop-ins

These drop-ins apply whole-service memory, task, file-descriptor, restart, and
filesystem-isolation controls to independently deployed Query and Search API
units. They are starting values, not universal capacity claims.

Install them only after the base units and paths exist:

```bash
sudo install -d -o getbible-query -g getbible-query /var/cache/getbible/query
sudo install -d -o getbible-search -g getbible-search /var/cache/getbible/search
sudo install -d -o root -g root /srv/getbible/mirror

sudo install -D -m 0644 \
  deploy/systemd/getbible-query.service.d/limits.conf \
  /etc/systemd/system/getbible-query.service.d/limits.conf
sudo install -D -m 0644 \
  deploy/systemd/getbible-search.service.d/limits.conf \
  /etc/systemd/system/getbible-search.service.d/limits.conf
sudo systemctl daemon-reload
sudo systemctl restart getbible-query.service getbible-search.service
```

Verify the effective configuration before traffic:

```bash
systemd-analyze verify getbible-query.service getbible-search.service
systemctl show getbible-query.service \
  -p MemoryHigh -p MemoryMax -p MemorySwapMax -p TasksMax -p LimitNOFILE
systemctl show getbible-search.service \
  -p MemoryHigh -p MemoryMax -p MemorySwapMax -p TasksMax -p LimitNOFILE
```

`MemoryHigh`, `MemoryMax`, and `TasksMax` cover every worker and thread in the
unit. Size them from measured peak RSS for the largest admitted translation and
every enabled normalization index. Do not increase them merely to hide an
unbounded cache, worker leak, or abusive search shape.

The files assume the immutable mirror is below `/srv/getbible/mirror` and the
services use separate writable caches. Change the paths in the drop-ins when
your base units use different locations. Keep Query and Search in separate
units so an expensive search cannot consume Query capacity.
