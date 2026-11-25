#!/bin/bash
# qcompile.sh <dir> : compile top.v in <dir> for EP4CE22F17C6 with extra.qsf, emit top.sof + top.rbf
set -e
Q=${QUARTUS_BIN:-$HOME/altera/13.1/quartus/bin}
d=$1; cd "$d"
cat > top.qsf <<Q
set_global_assignment -name FAMILY "Cyclone IV E"
set_global_assignment -name DEVICE EP4CE22F17C6
set_global_assignment -name TOP_LEVEL_ENTITY top
set_global_assignment -name VERILOG_FILE top.v
set_global_assignment -name RESERVE_ALL_UNUSED_PINS "AS INPUT TRI-STATED"
set_global_assignment -name GENERATE_RBF_FILE ON
set_global_assignment -name ON_CHIP_BITSTREAM_DECOMPRESSION OFF
set_global_assignment -name USE_CONFIGURATION_DEVICE OFF
set_global_assignment -name STRATIX_DEVICE_IO_STANDARD "3.3-V LVTTL"
set_global_assignment -name NUM_PARALLEL_PROCESSORS 1
set_global_assignment -name USE_CHECKSUM_AS_USERCODE OFF
set_global_assignment -name STRATIX_JTAG_USER_CODE FFFFFFFF
Q
[ -f extra.qsf ] && cat extra.qsf >> top.qsf
echo 'project_new top -overwrite' >/dev/null
$Q/quartus_map top >map.log 2>&1 && $Q/quartus_fit top >fit.log 2>&1 && $Q/quartus_asm top >asm.log 2>&1 || { echo "FAIL $d"; grep -h "Error" *.log | head -5; exit 1; }
[ -n "$EDA" ] && $Q/quartus_eda top --simulation --tool=modelsim --format=verilog >eda.log 2>&1
ls top.rbf >/dev/null
