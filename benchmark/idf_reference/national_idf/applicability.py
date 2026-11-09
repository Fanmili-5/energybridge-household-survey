"""Shared package/model-bound geographic evidence, independent of city labels."""


def bound_location_applicability(housing, target_city, evidence):
    if not isinstance(housing, dict) or not isinstance(evidence, dict):
        return False
    checks = evidence.get('checks') or {}
    cities = evidence.get('supported_cities')
    package = housing.get('package_id')
    model = housing.get('model')
    model_hash = model.get('sha256') if isinstance(model, dict) else None
    return (bool(target_city) and bool(package) and bool(model_hash)
            and evidence.get('status') == 'passed'
            and evidence.get('package_id') == package
            and evidence.get('model_sha256') == model_hash
            and isinstance(cities, list) and target_city in cities
            and bool(evidence.get('scope')) and isinstance(checks, dict)
            and bool(checks) and all(v is True for v in checks.values()))
