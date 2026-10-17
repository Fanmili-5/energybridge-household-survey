"""Population anchors remain fixed while explicitly constructed housing changes."""
from common import digest,read,OUT


def verify_fixed_family(before,after):
    keys=('household_id','N','G','H7','province','ego_relationships','random10_date_selection','role_policy')
    bad=[k for k in keys if before[k]!=after[k]]
    if before['H6']!=after['H6']:
        allocation=read(OUT/'AREA_REALLOCATION.json');hid=before['household_id']
        if allocation['configured_area_m2'].get(hid)!=after['H6']or allocation['original_area_m2'].get(hid)!=before['H6']:bad.append('unregistered_area_change')
    facts=('member_id','age_years','sex','employment_status','generation_level','ego_relation_code','reference_activity_role')
    for a,b in zip(before['members'],after['members']):
        bad.extend('member:'+k for k in facts if a[k]!=b[k])
    from housing_conditions import facets
    if facets(before)!=after['layout']['stock_reference_features']:bad.append('unregistered_configured_stock_facets')
    if bad:raise ValueError('Population anchors changed:'+','.join(bad))
    return {'passed':True,'anchor_sha256':digest({k:before[k]for k in keys}),
            'household_ID_roster_N_G_roomcount_province_dates_policy_unchanged':True,
            'H6_changed_under_registered_same_bin_global_projection':before['H6']!=after['H6']}
