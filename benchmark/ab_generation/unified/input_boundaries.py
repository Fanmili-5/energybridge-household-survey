"""Reject populated downstream answer/result fields at generation boundaries.

Null placeholders are permitted. This is a schema-field boundary, not a claim
to detect arbitrary hidden information in free-form text or opaque field names.
"""

DOWNSTREAM_FIELDS=frozenset({
    'human_acceptance','human_score','human_reason','human_answers',
    'actual_outcomes','physical_outcomes',
})


def require_no_downstream_fields(value,scope):
    pending=[((),value)]
    while pending:
        path,item=pending.pop()
        if isinstance(item,dict):
            for key,child in item.items():
                current=path+(str(key),)
                if key in DOWNSTREAM_FIELDS and child is not None:
                    raise ValueError('DOWNSTREAM_LABEL_OR_RESULT_IN_'+scope+':'+'.'.join(current))
                if isinstance(child,(dict,list,tuple)):pending.append((current,child))
        elif isinstance(item,(list,tuple)):
            pending.extend((path+(str(i),),child) for i,child in enumerate(item)
                           if isinstance(child,(dict,list,tuple)))
