// bf16_add: acc + prod -> BF16, round-to-nearest-even, combinational.
//
// Chains bf16_add_s1 (specials, order, align, add) and bf16_add_s2 (normalize,
// round, pack) with no register, so the T6 unit tests exercise exactly the
// logic the pipelined datapath uses. Implements R3, R7, R8, R9 (see the stage
// modules). Full BF16 range; subnormal inputs are read as zero.
`default_nettype none

module bf16_add (
    input  wire [15:0] a,       // accumulator
    input  wire [15:0] b,       // product
    output wire [15:0] y
);
    wire [11:0] sum;
    wire [7:0]  e_big;
    wire        s_big, spec;
    wire [15:0] spec_val;

    bf16_add_s1 u_s1 (.a(a), .b(b), .sum(sum), .e_big(e_big), .s_big(s_big),
                      .spec(spec), .spec_val(spec_val));
    bf16_add_s2 u_s2 (.sum(sum), .e_big(e_big), .s_big(s_big), .spec(spec),
                      .spec_val(spec_val), .y(y));
endmodule

`default_nettype wire
