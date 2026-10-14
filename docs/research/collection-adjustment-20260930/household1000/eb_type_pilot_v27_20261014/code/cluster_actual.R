library(cluster)
args <- commandArgs(trailingOnly=TRUE)
features <- read.csv(args[1],check.names=FALSE)
w <- as.numeric(strsplit(args[3],",",fixed=TRUE)[[1]])
stopifnot(nrow(features)==50,all(is.finite(as.matrix(features))),all(as.matrix(features)>=0),all(as.matrix(features)<=1))
# Explicit normalized0..1 anchors implement fixed scaling through the mature
# daisy routine. Bounds are not households and never enter PAM.
augmented <- rbind(features,rep(0,ncol(features)),rep(1,ncol(features)))
d <- as.matrix(daisy(augmented,metric="gower",weights=w))[1:50,1:50]
manual <- matrix(0,50,50)
for(i in 1:50)for(j in 1:50)manual[i,j]<-sum(w*abs(as.numeric(features[i,])-as.numeric(features[j,])))/sum(w)
stopifnot(max(abs(manual-d))<1e-12)
out <- data.frame(row=1:50)
quality <- data.frame()
for(k in 4:8){
 fit <- pam(as.dist(d),k=k,diss=TRUE,do.swap=TRUE)
 out[[paste0("k",k)]] <- fit$clustering
 quality <- rbind(quality,data.frame(k=k,silhouette=fit$silinfo$avg.width,
                  R=as.character(getRversion()),cluster=as.character(packageVersion("cluster")),fixed_range_error=max(abs(manual-d))))
}
write.csv(out,paste0(args[2],"_assignments.csv"),row.names=FALSE)
write.csv(quality,paste0(args[2],"_quality.csv"),row.names=FALSE)
