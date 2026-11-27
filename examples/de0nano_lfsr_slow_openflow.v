module top(input clk, output led);
  // prescaler 17 + 6 bits (2^23 clocks, ~0.17 s per step); LFSR steps on a registered tick
  reg [16:0] a = 0; reg ea = 0;
  reg [5:0]  b = 0; reg eb = 0;
  reg t2 = 0;
  reg [6:0]  l = 0;             // 7-bit XNOR LFSR, x^7 + x^6 + 1 (all-zero = power-up state is valid)
  wire t1 = a[16] & ~ea;
  always @(posedge clk) begin
    a <= a + 1'b1;  ea <= a[16];
    b <= b + t1;    eb <= b[5];
    t2 <= b[5] & ~eb;           // registered: the only net crossing down into (38,30)
    if (t2) l <= {l[5:0], ~(l[6] ^ l[5])};
  end
  assign led = l[0];            // l[0] at (38,30) N0 crosses up to LED0's register
endmodule
