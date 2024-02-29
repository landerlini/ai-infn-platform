VERSION=v0.5.1
mkdir -p crds/kueue
curl -L https://github.com/kubernetes-sigs/kueue/releases/download/$VERSION/manifests.yaml -o crds/kueue/manifest.yaml

