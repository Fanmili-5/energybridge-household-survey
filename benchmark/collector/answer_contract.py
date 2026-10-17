"""The role-preference instrument; objective simulation outcomes are separate."""
ANSWER_INSTRUCTIONS={
    'schema':'eb.role_preference_instrument.v69',
    'perspective':'按给定家庭角色，评价B相对A的调整是否适合这户家庭',
    'decision':{'question':'按这户家庭的情况，是否接受原样执行B？','choices':{'accept':'接受B方案','reject':'不接受B方案'}},
    'scores':{
        'score':{'label':'响应安排','meaning':'通知和操作是否适合这户家庭'},
        'comfort_score':{'label':'舒适与生活','meaning':'室温与生活变化是否适合这户家庭'},
        'energy_score':{'label':'用电安排','meaning':'用电量变化是否适合这户家庭'},
        'vpp_score':{'label':'VPP配合','meaning':'这种配合方式是否适合这户家庭'},
    },
    'range':[1,5],'anchors':{'1':'很不合适','5':'很合适'},'decimal_places':1,
    'reason':{'question':'最主要的原因','required':True},
    'objective_outcomes':'VPP是否达标单独记录，不预设家庭偏好或接受判断',
}
