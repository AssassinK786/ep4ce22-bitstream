module top(input clk, input key0, output led);
  reg k1 = 0, l = 0;              // power-up 0; KEY0 reads 1 while released
  always @(posedge clk) begin
    k1 <= key0;
    if (k1 & ~key0) l <= ~l;       // falling edge = press
  end
  assign led = l;
endmodule
