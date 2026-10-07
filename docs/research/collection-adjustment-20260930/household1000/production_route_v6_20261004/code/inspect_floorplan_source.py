"""Inspect new primary floor-plan archive without inventing metric scale.

Extract only semantic JPEGs and six paired review samples to private research.
Names, counts, dimensions and duplicate hashes are aggregate evidence, not
survey frequencies or observed H6/H7/door-vector labels.
"""
import collections,hashlib,json,subprocess
from pathlib import Path,PurePosixPath
from PIL import Image

OUT=Path(__file__).resolve().parent.parent
PRIVATE=OUT.parents[4]/'artifacts/private_research/production_route_v6_20261004'

def main():
    names=json.loads((OUT/'raw/floorplan3000_inventory.json').read_text())
    jpeg=[n for n in names if n.endswith('.jpg')]
    check={g:{} for g in ['2BR1WC','3BR1WC','3BR2WC','4BR2WC']}
    for name in jpeg:
        parts=PurePosixPath(name).parts
        assert not PurePosixPath(name).is_absolute() and '..' not in parts and len(parts)==4
        group,view,stem=parts[1],parts[2],parts[3]
        check[group].setdefault(stem,{})[view]=name
    assert all(set(views)=={'colorplan','plan','yuyi'} for records in check.values() for views in records.values())
    chosen=[views['yuyi'] for records in check.values() for views in records.values()]
    target=PRIVATE/'floorplan_samples';target.mkdir(exist_ok=True)
    listing=PRIVATE/'semantic_members.txt';listing.write_text('\n'.join(chosen)+'\n')
    subprocess.run(['tar','-xf',str(PRIVATE/'floorplans3000.rar'),'-C',str(target),'-T',str(listing)],check=True)
    dimensions=collections.Counter();metadata=collections.Counter();hashes=collections.defaultdict(list);groups=[]
    for group,records in check.items():
        group_hash=set()
        for stem,views in records.items():
            path=target/views['yuyi'];h=hashlib.sha256(path.read_bytes()).hexdigest();hashes[h].append(group+'/'+stem);group_hash.add(h)
            im=Image.open(path);dimensions[f'{im.width}x{im.height}']+=1;metadata[str(im.info.get('jfif_unit','missing'))]+=1
        groups.append({'catalogue_group':group,'paired_filename_sets':len(records),'unique_semantic_JPEG_bytes':len(group_hash),
                       'bedroom_WC_numbers_are_catalogue_labels_not_verified_census_H7':True})
    result={'doi':'10.17632/c49bkshg2w.1','url':'https://data.mendeley.com/datasets/c49bkshg2w/1','licence':'CC BY4.0; retain attribution; check any third_party_content',
      'contributor_name_as_published':'zc z','advertised_samples':3000,'actual_paired_filename_sets':len(chosen),'actual_JPEG_files':len(jpeg),
      'groups':groups,'semantic_byte_duplicate_groups':[v for v in hashes.values() if len(v)>1],
      'image_dimensions_pixels':dict(dimensions),'JFIF_unit_codes':dict(metadata),
      'machine_readable_metric_scale_or_geometry_files_in_archive':0,'room_door_window_vector_labels_in_archive':0,
      'visual_review_samples':['2BR1WC/a1.jpg','4BR2WC/d0.jpg'],'visible_door_and_window_symbols_in_two_plan_samples':True,
      'same_stem_does_not_prove_pixel_registration':'a1 colorplan visibly rescaled relative to plan/yuyi on equal642pixel_canvas; align_geometry_before_annotation',
      'colour_semantics_evidence':'labels in paired colorplan samples; no official machine-readable global codebook located',
      'national_frequency_or_province_representativeness_identified':False,'H6_or_shared_allocation_identified':False,
      'supports':'dimensionless_geometry_and_functional_reference_with_explicit_metric_reconstruction; human_verified_door_annotation_possible',
      'automatic_IDF_binding_approved':False,'new_1000_IDFs_from_this_source':0}
    (OUT/'FLOORPLAN_SOURCE_ADMISSION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'sets':len(chosen),'groups':groups,'byte_duplicate_groups':len(result['semantic_byte_duplicate_groups']),'sizes':len(dimensions)},indent=2))

if __name__=='__main__':main()
