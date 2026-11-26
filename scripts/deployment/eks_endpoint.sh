#!/usr/bin/env bash
# Set the addresses that may reach an EKS cluster's public API, and wait until EKS has applied it.
# .github/workflows/deploy-eks.yml opens the API to its runner with this, then puts the list back.
#
#   scripts/deployment/eks_endpoint.sh <cluster> <cidr,cidr,...>
#
# EKS runs one configuration update at a time (a few minutes each): this waits for one in progress first.
set -euo pipefail
cluster="$1" cidrs="$2"

wait_updates() {
  for _ in $(seq 1 90); do
    busy=$(aws eks list-updates --name "$cluster" --query 'updateIds' --output text | tr '\t' '\n' | while read -r id; do
      [ -n "$id" ] && aws eks describe-update --name "$cluster" --update-id "$id" --query 'update.status' --output text
    done | grep -c InProgress || true)
    [ "$busy" = "0" ] && return 0
    sleep 10
  done
  echo "an EKS update is still in progress after 15 minutes" >&2; return 1
}

current=$(aws eks describe-cluster --name "$cluster" --query 'cluster.resourcesVpcConfig.publicAccessCidrs' --output text | tr '\t' ',')
if [ "$(tr ',' '\n' <<<"$current" | sort | paste -sd,)" = "$(tr ',' '\n' <<<"$cidrs" | sort | paste -sd,)" ]; then
  echo "public access already: $cidrs"; exit 0
fi

wait_updates
id=$(aws eks update-cluster-config --name "$cluster" \
  --resources-vpc-config "endpointPublicAccess=true,publicAccessCidrs=$cidrs" --query 'update.id' --output text)
echo "update $id: public access -> $cidrs"
for _ in $(seq 1 90); do
  status=$(aws eks describe-update --name "$cluster" --update-id "$id" --query 'update.status' --output text)
  case "$status" in
    Successful) echo "applied"; exit 0 ;;
    Failed|Cancelled) aws eks describe-update --name "$cluster" --update-id "$id" --query 'update.errors' >&2; exit 1 ;;
  esac
  sleep 10
done
echo "update $id still $status after 15 minutes" >&2; exit 1
