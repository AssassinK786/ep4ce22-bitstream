module top(input clk, output led);
  reg [23:0] c = 0;
  always @(posedge clk) c <= c + 1'b1;
  assign led = c[23];
endmodule
