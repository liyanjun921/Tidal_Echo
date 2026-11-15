#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  printf '%s\n' '用法：' '  bash scripts/emoi_volume_backup.sh export /path/emoi-data.tar.gz' \
    '  bash scripts/emoi_volume_backup.sh restore /path/emoi-data.tar.gz NEW_VOLUME_NAME'
  exit 2
}
[[ $# -ge 2 ]] || usage
mode=$1
archive=$2
container=${EMOI_BACKUP_CONTAINER:-emoi-emoi-1}
image=$(sudo docker inspect -f '{{.Image}}' "$container")

case $mode in
  export)
    [[ $# -eq 2 && ! -e "$archive" && ! -L "$archive" ]] || usage
    tmp=$(mktemp "${archive}.partial.XXXXXXXX")
    running=$(sudo docker inspect -f '{{.State.Running}}' "$container")
    resume=false
    cleanup() {
      rm -f -- "$tmp"
      if [[ "$resume" == true ]]; then sudo docker start "$container" >/dev/null; fi
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    if [[ "$running" == true ]]; then
      resume=true
      sudo docker stop "$container" >/dev/null
    fi
    sudo docker run --rm --network none --volumes-from "$container":ro \
      --entrypoint tar "$image" -czf - -C /data . >"$tmp"
    tar -tzf "$tmp" >/dev/null
    ln -- "$tmp" "$archive"
    printf 'EMOI_BACKUP=%s\n' "$archive"
    ;;
  restore)
    [[ $# -eq 3 && -f "$archive" && "$3" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || usage
    volume=$3
    if sudo docker volume inspect "$volume" >/dev/null 2>&1; then
      printf '%s\n' '请指定一个尚不存在的新数据卷名称。'
      exit 2
    fi
    helper="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/emoi_volume_restore.py"
    sudo docker volume create "$volume" >/dev/null
    if ! sudo docker run --rm -i --network none \
      --mount "type=volume,src=$volume,dst=/restore" \
      --mount "type=bind,src=$helper,dst=/emoi_volume_restore.py,readonly" \
      --entrypoint python "$image" /emoi_volume_restore.py /restore <"$archive"; then
      sudo docker volume rm "$volume" >/dev/null
      exit 1
    fi
    printf 'EMOI_RESTORED_VOLUME=%s\n' "$volume"
    ;;
  *) usage ;;
esac
