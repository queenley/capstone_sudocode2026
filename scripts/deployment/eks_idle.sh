#!/usr/bin/env bash
# Pause the EKS shop when nobody needs it, and bring it back (docs/deployment/eks-deploy.md, section 5.1).
#
#   bash scripts/deployment/eks_idle.sh status
#   bash scripts/deployment/eks_idle.sh pause     # app to 0, nodes to 0: about 120-150 USD/month left (EKS, NAT, ALB, Valkey)
#   bash scripts/deployment/eks_idle.sh resume    # 2 system nodes, every app back to its minimum: 5-10 minutes
#
# Paused, the site answers 503 and the data stays: Aurora pauses itself, EFS, Valkey, the secrets and the images are
# kept. Nothing is deleted. `terraform plan` shows the node group's desired size as drift while paused: do not apply
# then, it would start the two nodes again. For weeks without a demo, section 5.2 (delete the cluster, keep the data)
# costs far less.
set -euo pipefail

CLUSTER="${CLUSTER:-telesales-production}"
NS="${NAMESPACE:-telesales-production}"
REGION="${AWS_REGION:-ap-southeast-1}"
export MSYS_NO_PATHCONV=1

nodegroup() {
  aws eks list-nodegroups --region "$REGION" --cluster-name "$CLUSTER" --query "nodegroups[0]" --output text
}

status() {
  local ng; ng=$(nodegroup)
  echo "node group $ng: $(aws eks describe-nodegroup --region "$REGION" --cluster-name "$CLUSTER" --nodegroup-name "$ng" \
    --query 'nodegroup.scalingConfig' --output json | tr -d '\n ')"
  echo "nodes: $(kubectl get nodes --no-headers 2>/dev/null | wc -l)  karpenter nodeclaims: $(kubectl get nodeclaims --no-headers 2>/dev/null | wc -l)"
  echo "app pods running: $(kubectl get pods -n "$NS" --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)"
}

pause() {
  local ng; ng=$(nodegroup)
  echo "1/4 KEDA holds the agent and the worker at 0 (or it would start them again)"
  kubectl annotate scaledobject --all -n "$NS" autoscaling.keda.sh/paused-replicas=0 --overwrite
  echo "2/4 every deployment to 0; the CronJobs suspended"
  kubectl scale deployment --all -n "$NS" --replicas=0
  for job in $(kubectl get cronjob -n "$NS" -o name); do kubectl patch "$job" -n "$NS" -p '{"spec":{"suspend":true}}'; done
  echo "3/4 waiting for Karpenter to give its nodes back"
  for _ in $(seq 1 60); do [ "$(kubectl get nodeclaims --no-headers 2>/dev/null | wc -l)" -eq 0 ] && break; sleep 10; done
  echo "4/4 the system node group to 0 (Karpenter itself runs there, so last)"
  aws eks update-nodegroup-config --region "$REGION" --cluster-name "$CLUSTER" --nodegroup-name "$ng" \
    --scaling-config minSize=0,maxSize=3,desiredSize=0 >/dev/null
  echo "Paused. Resume with: bash scripts/deployment/eks_idle.sh resume"
}

resume() {
  local ng; ng=$(nodegroup)
  echo "1/4 the system node group back to 2"
  aws eks update-nodegroup-config --region "$REGION" --cluster-name "$CLUSTER" --nodegroup-name "$ng" \
    --scaling-config minSize=2,maxSize=3,desiredSize=2 >/dev/null
  echo "2/4 waiting for 2 nodes Ready (3-5 minutes)"
  for _ in $(seq 1 60); do
    [ "$(kubectl get nodes --no-headers 2>/dev/null | grep -c ' Ready')" -ge 2 ] && break; sleep 10
  done
  echo "3/4 every deployment back to 1 (the HPAs and KEDA take it from there); the CronJobs resumed"
  kubectl scale deployment --all -n "$NS" --replicas=1
  for job in $(kubectl get cronjob -n "$NS" -o name); do kubectl patch "$job" -n "$NS" -p '{"spec":{"suspend":false}}'; done
  kubectl annotate scaledobject --all -n "$NS" autoscaling.keda.sh/paused-replicas-
  echo "4/4 waiting for the rollouts"
  for deployment in $(kubectl get deploy -n "$NS" -o name); do kubectl rollout status "$deployment" -n "$NS" --timeout=10m; done
  echo "Resumed."
}

case "${1:-status}" in
  pause) pause ;;
  resume) resume ;;
  status) status ;;
  *) echo "usage: $0 pause|resume|status" >&2; exit 2 ;;
esac
