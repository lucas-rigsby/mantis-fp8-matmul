// mantis_dp_pe4: T7 organization (a), four parallel MAC processing elements.
//
// REFERENCE PROTOTYPE ONLY: not used by tt_um_mantis (organization (b),
// mantis_dp_shared, was chosen). Its single-stage adder misses 20 ns at
// ss_100C_1v60 (22.6 ns); see docs/feasibility.md. Kept for comparison and
// still exercised by tb/test_datapath.py.
//
// Pipeline (issue = 4th WRITE sampled at edge t0):
//   edge t0   : b1_r <= din, v1 <= 1
//   cycle t0  : 4 multipliers on slot0..2 (still holding step k) and b1_r
//   edge t0+1 : product registers <= products, v2 <= 1
//   cycle t0+1: 4 adders acc + product
//   edge t0+2 : accumulators commit (R1, R3); busy falls -> drain = 2 (R11)
// Slot 0 is first overwritten at edge t0+1, after the products are taken.
// Steps can issue every 4 clocks (R10); they commit in order (P11).
// CLEAR or reset clears v1/v2 and the accumulators at the same edge, so no
// pre-CLEAR step can commit afterwards (R13, P10).
`default_nettype none

module mantis_dp_pe4 (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    input  wire [1:0]  cmd,
    input  wire [7:0]  din,
    output wire        busy,        // R11, P2
    output wire [63:0] acc,         // {C11, C10, C01, C00}
    output wire        fmt_a,
    output wire        fmt_b,
    output wire [1:0]  n
);
    wire [7:0] a0, a1, b0;
    wire       issue, clear;

    mantis_stage u_stage (.clk(clk), .rst_n(rst_n), .in_valid(in_valid), .cmd(cmd),
                          .din(din), .a0(a0), .a1(a1), .b0(b0), .issue(issue),
                          .clear(clear), .fmt_a(fmt_a), .fmt_b(fmt_b), .n(n));

    reg  [7:0]  b1_r;
    reg         v1, v2;
    reg  [15:0] p00, p01, p10, p11;
    reg  [15:0] c00, c01, c10, c11;

    wire [15:0] m00, m01, m10, m11, s00, s01, s10, s11;
    fp8_mul u_m00 (.a(a0), .b(b0),   .fmt_a(fmt_a), .fmt_b(fmt_b), .p(m00));
    fp8_mul u_m01 (.a(a0), .b(b1_r), .fmt_a(fmt_a), .fmt_b(fmt_b), .p(m01));
    fp8_mul u_m10 (.a(a1), .b(b0),   .fmt_a(fmt_a), .fmt_b(fmt_b), .p(m10));
    fp8_mul u_m11 (.a(a1), .b(b1_r), .fmt_a(fmt_a), .fmt_b(fmt_b), .p(m11));
    bf16_add u_s00 (.a(c00), .b(p00), .y(s00));
    bf16_add u_s01 (.a(c01), .b(p01), .y(s01));
    bf16_add u_s10 (.a(c10), .b(p10), .y(s10));
    bf16_add u_s11 (.a(c11), .b(p11), .y(s11));

    // control and accumulators (reset / CLEAR priority: R13, R14)
    always @(posedge clk) begin
        if (!rst_n || clear) begin
            v1 <= 1'b0;  v2 <= 1'b0;
            c00 <= 16'h0000; c01 <= 16'h0000; c10 <= 16'h0000; c11 <= 16'h0000;
        end else begin
            v1 <= issue;
            v2 <= v1;
            if (v2) begin
                c00 <= s00; c01 <= s01; c10 <= s10; c11 <= s11;
            end
        end
    end

    // data registers (not reset)
    always @(posedge clk) begin
        if (issue) b1_r <= din;
        if (v1) begin
            p00 <= m00; p01 <= m01; p10 <= m10; p11 <= m11;
        end
    end

    assign busy = v1 | v2;
    assign acc  = {c11, c10, c01, c00};
endmodule

`default_nettype wire
