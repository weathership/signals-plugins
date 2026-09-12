#!/usr/bin/env bash
# Compile Protocol Buffers for the Hermes lattice engine.
#
# Usage: ./scripts/compile_engine_protos.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NATIVE="$ROOT/hsengine/engine/proto"
# Generated stubs ship in-tree. Regen needs a signals-protocol checkout.
ZNDX="${SIGNALS_PROTOCOL_PROTO:-}"
if [[ -z "$ZNDX" ]]; then
  for cand in \
    "$ROOT/../signals/external/signals-protocol/proto" \
    "$ROOT/../oss/hermes-agent/components/signals-protocol/proto" \
    "${HOME}/local/src/oss/hermes-agent/components/signals-protocol/proto"; do
    if [[ -f "$cand/zndx/engine/v1/engine.proto" ]]; then
      ZNDX="$cand"
      break
    fi
  done
fi
OUT="$ROOT/hsengine/engine/generated"

if [[ -z "$ZNDX" || ! -f "$ZNDX/zndx/engine/v1/engine.proto" ]]; then
  echo "Error: signals-protocol proto tree not found. Set SIGNALS_PROTOCOL_PROTO." >&2
  exit 1
fi

if ! python -c "import grpc_tools.protoc" 2>/dev/null; then
  echo "Error: grpcio-tools not installed. pip install -e .  (signals-hsengine)" >&2
  exit 1
fi

mkdir -p "$OUT"
touch "$OUT/__init__.py"

echo "Compiling hermes.engine.HermesEngine"
python -m grpc_tools.protoc \
  -I "$NATIVE" \
  --python_out="$OUT" --pyi_out="$OUT" --grpc_python_out="$OUT" \
  "$NATIVE/hermes_engine.proto"

echo "Compiling hsengine.opening.Catalog"
python -m grpc_tools.protoc \
  -I "$NATIVE" \
  --python_out="$OUT" --pyi_out="$OUT" \
  "$NATIVE/opening.proto"

echo "Compiling zndx.engine.v1.Engine"
python -m grpc_tools.protoc \
  -I "$ZNDX" \
  --python_out="$OUT" --pyi_out="$OUT" --grpc_python_out="$OUT" \
  "$ZNDX/zndx/engine/v1/engine.proto"

echo "Compiling zndx.supervision.v1.EngineSupervision"
python -m grpc_tools.protoc \
  -I "$ZNDX" \
  --python_out="$OUT" --pyi_out="$OUT" --grpc_python_out="$OUT" \
  "$ZNDX/zndx/supervision/v1/supervision.proto"

# The Signals engine's scheduler face: the ENGINE declares coordination
# Activities there (Declare/Renew/Release/Watch) on behalf of local processes
# such as the interactive session. Local processes never import this stub.
echo "Compiling zndx.scheduler.v1.Scheduler"
python -m grpc_tools.protoc \
  -I "$ZNDX" \
  --python_out="$OUT" --pyi_out="$OUT" --grpc_python_out="$OUT" \
  "$ZNDX/zndx/scheduler/v1/scheduler.proto"

echo "Compiling zndx.agent.v1.Agents"
python -m grpc_tools.protoc \
  -I "$ZNDX" \
  --python_out="$OUT" --pyi_out="$OUT" --grpc_python_out="$OUT" \
  "$ZNDX/zndx/agent/v1/agent.proto"

echo "Compiling inference.GRPCInferenceService (OIP)"
python -m grpc_tools.protoc \
  -I "$ZNDX" \
  --python_out="$OUT" --pyi_out="$OUT" --grpc_python_out="$OUT" \
  "$ZNDX/inference/v2/open_inference_grpc.proto"

mkdir -p \
  "$OUT/zndx/engine/v1" \
  "$OUT/zndx/supervision/v1" \
  "$OUT/zndx/scheduler/v1" \
  "$OUT/zndx/agent/v1" \
  "$OUT/inference/v2"
touch \
  "$OUT/zndx/__init__.py" \
  "$OUT/zndx/engine/__init__.py" \
  "$OUT/zndx/engine/v1/__init__.py" \
  "$OUT/zndx/supervision/__init__.py" \
  "$OUT/zndx/supervision/v1/__init__.py" \
  "$OUT/zndx/scheduler/__init__.py" \
  "$OUT/zndx/scheduler/v1/__init__.py" \
  "$OUT/zndx/agent/__init__.py" \
  "$OUT/zndx/agent/v1/__init__.py" \
  "$OUT/inference/__init__.py" \
  "$OUT/inference/v2/__init__.py"

# grpc_tools emits absolute imports; rewrite into the hsengine package.
sed -i 's/^import hermes_engine_pb2/from . import hermes_engine_pb2/' \
  "$OUT/hermes_engine_pb2_grpc.py"
sed -i 's/^from zndx\.engine\.v1 import/from hsengine.engine.generated.zndx.engine.v1 import/' \
  "$OUT/zndx/engine/v1/engine_pb2_grpc.py"
if [[ -f "$OUT/zndx/supervision/v1/supervision_pb2_grpc.py" ]]; then
  sed -i 's/^from zndx\.supervision\.v1 import/from hsengine.engine.generated.zndx.supervision.v1 import/' \
    "$OUT/zndx/supervision/v1/supervision_pb2_grpc.py"
fi
if [[ -f "$OUT/zndx/scheduler/v1/scheduler_pb2_grpc.py" ]]; then
  sed -i 's/^from zndx\.scheduler\.v1 import/from hsengine.engine.generated.zndx.scheduler.v1 import/' \
    "$OUT/zndx/scheduler/v1/scheduler_pb2_grpc.py"
  # scheduler.proto imports engine.proto: the pb2 module resolves it absolutely.
  sed -i 's/^from zndx\.engine\.v1 import engine_pb2 as /from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as /' \
    "$OUT/zndx/scheduler/v1/scheduler_pb2.py" "$OUT/zndx/scheduler/v1/scheduler_pb2.pyi"
fi
if [[ -f "$OUT/zndx/agent/v1/agent_pb2_grpc.py" ]]; then
  sed -i 's/^from zndx\.agent\.v1 import/from hsengine.engine.generated.zndx.agent.v1 import/' \
    "$OUT/zndx/agent/v1/agent_pb2_grpc.py"
  sed -i 's/^from zndx\.engine\.v1 import engine_pb2 as /from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as /' \
    "$OUT/zndx/agent/v1/agent_pb2.py" "$OUT/zndx/agent/v1/agent_pb2.pyi"
fi
if [[ -f "$OUT/inference/v2/open_inference_grpc_pb2_grpc.py" ]]; then
  sed -i 's/^from inference\.v2 import/from hsengine.engine.generated.inference.v2 import/' \
    "$OUT/inference/v2/open_inference_grpc_pb2_grpc.py"
  sed -i 's/^import open_inference_grpc_pb2/from . import open_inference_grpc_pb2/' \
    "$OUT/inference/v2/open_inference_grpc_pb2_grpc.py"
fi

echo "OK generated → $OUT"
