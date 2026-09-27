// PETG ceiling saddle for a 16.3 mm pole.
//
// The hole is a full circle, open at both ends. Slide the pole in from
// either end. Nothing crosses the bore.
//
// A screw tab comes out of each side. The tabs stop at the saddle wall,
// so they never enter the hole. A solid top wall keeps the pole about
// 3.6 mm below the ceiling.
//
// Print in PETG, tabs on the bed:
//   0.4 mm nozzle, 0.20 mm layers, 4+ perimeters, 40%+ infill, no supports.
//
// Hardware: two #8 / M4 pan-head screws, about 25 mm or longer.

/* [Pole] */
pole_diameter = 16.3;     // caliper measurement, side to side
fit_clearance = 0.60;     // bore oversize. 0.4 is snug, 0.8 is easy

/* [Clip] */
strap_width = 20.0;       // length along the pole
wall = 4.2;               // radial wall of the saddle
top_wall = 3.2;           // plastic between the pole and the ceiling
tab_thickness = 4.8;
tab_length = 20.0;        // stick-out of each tab past the saddle
tab_width = 20.0;         // along the pole
corner_radius = 3.0;
tab_overlap = 6.0;        // how far each tab buries into the saddle wall

/* [Screws] */
screw_diameter = 4.5;     // clearance for #8 / M4
head_diameter = 8.6;
head_depth = 2.6;

/* [Preview] */
show_pole = true;

bore_d = pole_diameter + fit_clearance;
bore_r = bore_d / 2;
outer_r = bore_r + wall;
eps = 0.05;

// Ceiling is Z = 0. The bore is a full circle below the top wall.
cz = -(top_wall + bore_r);

// Hole center is midway along the free part of each tab.
screw_x = outer_r + (tab_length - head_diameter) / 2 - 1.0;

module rounded_plate(length, width, thickness, radius) {
    // Plate is centered on X and Y. Bottom is Z = 0.
    hull() {
        for (sx = [-1, 1], sy = [-1, 1]) {
            translate([
                sx * (length / 2 - radius),
                sy * (width / 2 - radius),
                0
            ]) cylinder(h = thickness, r = radius, $fn = 36);
        }
    }
}

module screw_hole() {
    // Local Z = 0 is the room-side face of the tab.
    cylinder(h = tab_thickness + 2 * eps, d = screw_diameter, $fn = 36);
    translate([0, 0, -eps])
        cylinder(h = head_depth + eps, d1 = head_diameter, d2 = screw_diameter, $fn = 36);
    translate([0, 0, -head_depth])
        cylinder(h = head_depth + eps, d = head_diameter, $fn = 36);
}

module side_tab(side) {
    // side is -1 or +1. The tab overlaps the saddle, then sticks outward.
    span = tab_length + tab_overlap;
    translate([
        side * (outer_r - tab_overlap + span / 2),
        0,
        -tab_thickness
    ])
        rounded_plate(span, tab_width, tab_thickness, corner_radius);

    // Gusset under the root so the tab is not a sharp step.
    hull() {
        translate([side * (outer_r - 0.6), 0, -tab_thickness])
            cube([1.2, tab_width - 6, 1.2], center = true);
        translate([side * (outer_r + 7), 0, -tab_thickness])
            cube([1.2, tab_width - 10, 1.2], center = true);
        translate([side * (outer_r - 0.4), 0, cz + 1.5])
            cube([1.2, strap_width - 4, 1.2], center = true);
    }
}

module saddle() {
    difference() {
        union() {
            translate([0, -strap_width / 2, cz])
                rotate([-90, 0, 0])
                    cylinder(h = strap_width, r = outer_r, $fn = 128);

            side_tab(-1);
            side_tab(1);
        }

        // Full round bore. This is the only opening the pole uses.
        translate([0, -(strap_width / 2 + eps), cz])
            rotate([-90, 0, 0])
                cylinder(h = strap_width + 2 * eps, r = bore_r, $fn = 128);

        // Shave the crown only. This cut stays inside the bore width so
        // it cannot remove either tab.
        translate([-bore_r - 0.2, -(strap_width / 2 + eps), 0])
            cube([bore_d + 0.4, strap_width + 2 * eps, outer_r + 2]);

        lead = 1.0;
        translate([0, -(strap_width / 2 + eps), cz])
            rotate([-90, 0, 0])
                cylinder(h = lead + eps, r1 = bore_r + 0.7, r2 = bore_r, $fn = 72);
        translate([0, strap_width / 2 - lead, cz])
            rotate([-90, 0, 0])
                cylinder(h = lead + eps, r1 = bore_r, r2 = bore_r + 0.7, $fn = 72);

        translate([-screw_x, 0, -tab_thickness - eps]) screw_hole();
        translate([ screw_x, 0, -tab_thickness - eps]) screw_hole();
    }
}

module preview_pole() {
    color([0.75, 0.55, 0.25, 0.35])
        translate([0, -strap_width, cz])
            rotate([-90, 0, 0])
                cylinder(h = strap_width * 2, d = pole_diameter, $fn = 72);
}

saddle();
if (show_pole) preview_pole();
