from app import create_app

app = create_app()

for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
    print("{} -> {}".format(rule, rule.endpoint))
