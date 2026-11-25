project_open top
create_timing_netlist
read_sdc
update_timing_netlist
report_path -from [get_ports *] -to [get_ports y] -npaths 10 -show_routing -file paths.rpt
