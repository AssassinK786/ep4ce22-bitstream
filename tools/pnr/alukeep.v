// Black box that keeps Yosys $alu cells intact for carry-chain mapping in pnr.py
(* blackbox *)
module ALUKEEP #(parameter A_SIGNED = 0, parameter B_SIGNED = 0, parameter A_WIDTH = 1,
                 parameter B_WIDTH = 1, parameter Y_WIDTH = 1) (
    input [A_WIDTH-1:0] A, input [B_WIDTH-1:0] B, input CI, input BI,
    output [Y_WIDTH-1:0] X, output [Y_WIDTH-1:0] Y, output [Y_WIDTH-1:0] CO);
endmodule
