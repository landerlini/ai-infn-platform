VERSION=v0.5.1
mkdir -p templates/kueue
curl -L https://github.com/kubernetes-sigs/kueue/releases/download/$VERSION/manifests.yaml -o templates/kueue/manifest.yaml

