#!/usr/bin/env bash
# =================================================
#  Animeko 一键去"相关推荐"工具入口
#  用法: ./animeko_patch.sh <原版APK路径> [输出APK路径]
#  依赖: python3, baksmali, smali, apksigner, keystore
# =================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$SCRIPT_DIR/remove_recommend.py"

# ---- 可配置项（也可通过环境变量覆盖）----
KS="${KS:-/tmp/modkey.jks}"          # keystore 路径
export KS
export KS_ALIAS="${KS_ALIAS:-animeko}"
export KS_PASS="${KS_PASS:-123456}"
export KEY_PASS="${KEY_PASS:-123456}"

if [ $# -lt 1 ]; then
    echo "用法: $0 <原版APK路径> [输出APK路径]"
    exit 1
fi
IN_APK="$1"
if [ ! -f "$IN_APK" ]; then
    echo "[!] 找不到 APK: $IN_APK"
    exit 1
fi
OUT="${2:-}"
# smali 汇编 API 级别：必须为 35，否则接口 default 方法标志丢失导致应用闪退
API="${API:-35}"
ARGS=("$IN_APK" --api "$API")
if [ -n "$OUT" ]; then
    ARGS+=(--out "$OUT")
fi

echo "=========================================="
echo " Animeko 一键去相关推荐工具"
echo " 输入: $IN_APK"
echo " Keystore: $KS"
echo "=========================================="
echo "运行工具中……（此过程需反编译多个 dex，请耐心等待）"
echo
python3 "$TOOL" "${ARGS[@]}"
RC=$?
echo
if [ $RC -eq 0 ]; then
    echo "✅ 全部完成！请到输出目录取用签名 APK。"
else
    echo "❌ 执行出错 (exit=$RC)，请查看上面的日志。"
fi
exit $RC