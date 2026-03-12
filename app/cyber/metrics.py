from prometheus_client import Counter, Gauge

# Compteurs
cyber_threats_total = Counter('cyber_threats_total', 'Total number of detected threats', ['agent', 'tool'])
cyber_quarantine_total = Counter('cyber_quarantine_total', 'Total number of quarantine actions', ['agent', 'tool'])
cyber_lures_total = Counter('cyber_lures_total', 'Total number of lures deployed', ['type'])

# Jauges
active_quarantine = Gauge('active_quarantine', 'Number of tools currently in quarantine')
signature_count = Gauge('signature_count', 'Number of known threat signatures')