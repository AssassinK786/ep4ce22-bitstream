module top(input clk, output [7:0] led);
  reg [24:0] c = 0;
  always @(posedge clk) c <= c + 1'b1;
  assign led = c[24:17];    // LED7 = c[24] toggles every ~0.34 s, LED0 = c[17] every ~2.6 ms
endmodule
