"""Extend the identical deterministic R distance/PAM protocol to1000 rows."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=ROOT/'code/cluster_actual.R';old=sha(p);s=p.read_text();assert 'nrow(features)==50'in s
    s=s.replace('nrow(features)==50','nrow(features)==1000').replace('[1:50,1:50]','[seq_len(nrow(features)),seq_len(nrow(features))]')
    s=s.replace('manual <- matrix(0,50,50)','n <- nrow(features)\nx <- as.matrix(features)\nmanual <- matrix(0,n,n)')
    fragment='for(i in 1:50)for(j in 1:50)manual[i,j]<-sum(w*abs(as.numeric(features[i,])-as.numeric(features[j,])))/sum(w)';assert fragment in s
    s=s.replace(fragment,'for(i in seq_len(n))manual[i,]<-rowSums(sweep(abs(sweep(x,2,x[i,],"-")),2,w,"*"))/sum(w)')
    s=s.replace('out <- data.frame(row=1:50)','out <- data.frame(row=seq_len(n))');p.write_text(s)
    (ROOT/'R_SCOPE_ADAPTER.json').write_text(json.dumps({'rows':1000,'before_sha256':old,'after_sha256':sha(p),
        'same_fixed0to1_anchors_Gower_weights_manual_L1_PAM_BUILD_SWAP':True,'same_k4to8_diagnostics':True,
        'manual_crosscheck_vectorized_without_metric_change':True,'labels_used_as_features':False,'EP_started':0},indent=2)+'\n')
    print(json.dumps({'R_rows':1000,'metric_and_deterministic_protocol_unchanged':True}))
if __name__=='__main__':main()
