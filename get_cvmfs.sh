VERSION=2.3
URL=https://raw.githubusercontent.com/cvmfs-contrib/cvmfs-csi/release-$VERSION/deployments/kubernetes
OUTPUT_FILE=crds/cvmfs/manifest.yaml
mkdir -p crds/cvmfs
curl -L $URL/controllerplugin-deployment.yaml > $OUTPUT_FILE
echo '---' >> $OUTPUT_FILE
curl -L $URL/controllerplugin-rbac.yaml >> $OUTPUT_FILE
echo '---' >> $OUTPUT_FILE
curl -L $URL/csidriver.yaml >> $OUTPUT_FILE
echo '---' >> $OUTPUT_FILE
curl -L $URL/nodeplugin-daemonset.yaml >> $OUTPUT_FILE



