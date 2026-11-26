module top(input clk, input [1:0] key, input [3:0] sw, output [4:0] led);
  reg [3:0] s = 0;
  always @(posedge clk) s <= sw;
  assign led[0]   = ~key[0];      // KEY0 is active low: LED0 lights while KEY0 is pressed
  assign led[4:1] = s;            // LED1..LED4 follow SW0..SW3
endmodule
