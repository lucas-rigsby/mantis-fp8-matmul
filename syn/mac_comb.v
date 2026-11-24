// Synthesis-only wrapper (T6 gate): fp8_mul feeding bf16_add as one
// combinational path, to measure the single-cycle MAC critical path.
// Not part of the design RTL.
`default_nettype none

module mac_comb (
    input  wire [7:0]  a,
    input  wire [7:0]  b,
    input  wire        fmt_a,
    input  wire        fmt_b,
    input  wire [15:0] acc,
    output wire [15:0] acc_next
);
    wire [15:0] p;
    fp8_mul  u_mul (.a(a), .b(b), .fmt_a(fmt_a), .fmt_b(fmt_b), .p(p));
    bf16_add u_add (.a(acc), .b(p), .y(acc_next));
endmodule

`default_nettype wire
