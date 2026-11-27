module top(input clk, output led);
  // 25-bit counter as two carry chains (17 + 8 bits); LED0 = bit 24 -> toggles every 2^24 clocks (~0.34 s)
  reg [16:0] a = 0; reg e = 0;
  reg [7:0]  b = 0;
  wire t = a[16] & ~e;          // a wraps every 2^17 clocks
  always @(posedge clk) begin
    a <= a + 1'b1;  e <= a[16];
    b <= b + t;
  end
  assign led = b[7];
endmodule
