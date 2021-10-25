from bisect import insort_left
import argparse
import numpy as np
import matplotlib.pyplot as plt


class Frame:
    def __init__(self, index, value):
        self.index = index
        self.value = value
        self.assigned = 0.0

    def __lt__(self, other):
        if self.value == other.value:
            return self.index > other.index

        return self.value < other.value

    def assign(self, amount):
        self.value += amount
        self.assigned += abs(amount)


class PriceFrame(Frame):
    def assign(self, amount):
        self.assigned += abs(amount)


class ArgumentError(Exception):
    def __init__(self, message):
        self.message = message


def read_curve(path):
    with open(path) as file:
        data = file.readlines()
        data = [float(datum.rstrip()) for datum in data]

    return data


def append(list, item):
    """Can be used instead of insort_left when optimizing with price curves."""
    list.append(item)


def mean_curve(values, samples=72):
    """
    Creates a curve containing the moving average of each point in the original. The default 72
    samples means that the previous 36 hours and following 35 hours will be used to generate the
    moving average for the current hour.
    """
    margin = int(samples / 2)
    wrapped = values[len(values) - margin :] + values + values[:margin]

    return np.resize(
        np.convolve(wrapped, np.ones(samples), "valid") / samples,
        len(values),
    )


def target_curves(load_curve, mean_curve):
    """
    Given the load curve and moving average mean curve, returns two new curves describing the amount
    of charging or discharging which would be needed in each hour for a new curve to match the mean.
    """
    deviation_curve = np.array(load_curve) - np.array(mean_curve)

    charging_target = [-value if value < 0.0 else 0.0 for value in deviation_curve]

    discharging_target = [
        min(value, load_curve[index]) if value > 0.0 else 0.0
        for (index, value) in enumerate(deviation_curve)
    ]

    return (charging_target, discharging_target)


def optimize(
    data,
    charging_target,
    discharging_target,
    capacity=5000.0,
    gradual=False,
    lookbehind=72,
    price_curve=None,
    volume=50000.0,
):
    """
    Runs the optimization. Returns the energy stored in the battery in each hour.

    Arguments:
    data               - The residual load curve
    charging_target    - Curve describing the desired charging in each hour
    discharging_target - Curve describing the desired discharging in each hour

    Keyword arguments:
    volume      - The volume of the battery in MWh.
    capacity    - The volume of the battery in MW.
    lookbehind  - How many hours the algorithm can look into the past to search for the minimum.
    price_curve - An optional price curve. If given, the algorithm will optimize for profit using
                  the price curve rather than flattening the load curve.
    """
    optimize_profit = price_curve != None

    insort_max = append if optimize_profit else insort_left

    # All values for the year converted to a Frame.
    if optimize_profit:
        frames = [PriceFrame(index, value) for (index, value) in enumerate(price_curve)]
    else:
        frames = [Frame(index, value) for (index, value) in enumerate(data)]

    # Contains all hours where there is room to discharge, sorted in ascending order (highest value
    # is last).
    charge_frames = sorted(
        [frame for frame in frames if discharging_target[frame.index] > 0]
    )

    # Keeps track of how much energy is in the reserve in each hour.
    reserve = np.zeros(len(data))

    # Keeps track of how much energy has been assigned in each hour.
    # assigned = np.zeros(len(data))

    # Convert the charging and discharging targets to ndarray, constrained by the capacity of the
    # battery.
    charging_target = np.array([min(capacity, value) for value in charging_target])
    discharging_target = np.array(
        [min(capacity, value) for value in discharging_target]
    )

    while len(charge_frames) > 0:
        max_frame = charge_frames.pop()

        # Eventually contains the amount of energy to be charged at the min and discharged at the
        # max frames.
        available_energy = discharging_target[max_frame.index]

        # The frame cannot be discharged any further (no margin between current and target load or
        # the battery is already at max capacity).
        if available_energy == 0:
            continue

        # Only charge from an hour whose value is 95% or lower than the max.
        desired_low = max_frame.value * 0.95

        # Contains the hour within the lookbehind periods with the minimum value.
        min_frame = None

        for min_index in range(
            max_frame.index - 1, max(0, max_frame.index - lookbehind) - 1, -1
        ):
            if reserve[min_index] >= volume:
                # We've reached a frame already at max-capacity; therefore neither it nor an earlier
                # frame will be able to charge.
                break

            current = frames[min_index]

            # Limit charging by the remaining volume in the frame.
            available_energy = min(available_energy, volume - reserve[min_index])

            if (
                available_energy > 0
                and charging_target[current.index] > 0
                and (not min_frame or current.value < min_frame.value)
                and current.value < desired_low
            ):
                min_frame = current

        # We now have either the min frame, or None in which case no optimisation can be performed
        # on the max frame.
        if min_frame == None:
            continue

        # Contrain the charge/discharge by the charging target.
        available_energy = min(available_energy, charging_target[min_frame.index])

        if gradual and not optimize_profit:
            # Take the half-way point between the peak and trough, if possible.
            upper = max_frame.value
            lower = min_frame.value

            # Restrict the amount of energy assigned to be one twentieth of the difference between
            # the max and min. This allows energy to be assigned more fairly to surrounding hours in
            # later iterations.
            available_energy = min(available_energy, (upper - lower) / 10)

        if available_energy == 0:
            continue

        # Add the charge and discharge to the reserve.
        reserve[(min_frame.index) : (max_frame.index)] += available_energy

        min_frame.assign(available_energy)
        max_frame.assign(-available_energy)

        charging_target[min_frame.index] -= available_energy
        discharging_target[max_frame.index] -= available_energy

        if discharging_target[max_frame.index] > 0:
            insort_max(charge_frames, max_frame)

    return reserve


def build_targets(args, loads, capacity):
    if args.constraints_path == False:
        if not args.price_path:
            raise ArgumentError(
                "argument --no-constrain: requires that --price also be specified"
            )
        return (np.repeat(capacity, len(loads)), np.repeat(capacity, len(loads)))

    if args.constraints_path:
        charge = np.zeros(len(loads))
        discharge = np.zeros(len(loads))

        for (index, value) in enumerate(read_curve(args.constraints_path)):
            if value < 0:
                discharge[index] = abs(value)
            else:
                charge[index] = abs(value)

        return (charge, discharge)

    # If we are still missing a curve, it will be based on the moving average of the load.

    return target_curves(loads, mean_curve(loads))


def run(args):
    """
    Runs the optimization using the args provided on the command-line.
    """
    capacity = args.capacity or args.volume / 10
    loads = read_curve(args.input_path)
    prices = read_curve(args.price_path) if args.price_path else None

    (charging_target, discharging_target) = build_targets(args, loads, capacity)

    if not prices and not args.constraints_path:
        # When optimizing towards the mean, the algorithm produces better results when each value is
        # converted to the difference between itself and the target. This means that instead of
        # matching the absolute max with the absolute mean, we find hours which are furthest from
        # the target curves.
        relative_loads = np.array(loads) - np.array(mean_curve(loads))
    else:
        relative_loads = loads

    reserve = optimize(
        relative_loads,
        charging_target,
        discharging_target,
        capacity=capacity,
        gradual=args.gradual,
        lookbehind=args.window,
        price_curve=prices,
        volume=args.volume,
    )

    with open(args.output_path, "w") as file:
        if prices == None:
            file.write("index,residual_load,adjusted_load,charge,soc\n")
        else:
            file.write("index,residual_load,adjusted_load,charge,soc,price\n")

        prev_load = 0.0
        for index in range(0, len(loads)):
            charge = reserve[index] - prev_load

            file.write(str(index))
            file.write(",")
            file.write(str(loads[index]))
            file.write(",")
            file.write(str(loads[index] + charge))
            file.write(",")
            file.write(str(charge))
            file.write(",")
            file.write(str(reserve[index]))
            if prices != None:
                file.write(",")
                file.write(str(prices[index]))
            file.write("\n")

            prev_load = reserve[index]

    create_plot(loads, reserve)

def create_plot(loads_array, reserve_array):

    # Initialise plot
    plt.close()
    fig, ax = plt.subplots(figsize=(25,10))
    plt.subplot(2,1,1)
    plt.title("P2P behaviour")
    plt.xlabel("time (hours)")
    plt.ylabel("MW")

    # Creating the adjusted residual load curve

    charge = np.diff(reserve_array)
    charge = np.insert(charge, 1, 0.0)

    #### Plotting curves
    plot_max = 500
    plt.plot(np.array(range(0,plot_max)), loads_array[0:plot_max], label="Residual Load")
    plt.plot(np.array(range(0,plot_max)), loads_array[0:plot_max] + charge[0:plot_max], label="Adjusted Residual Load")

    plt.subplot(2,1,2)
    plt.title("P2P State of Charge")
    plt.xlabel("time (hours)")
    plt.ylabel("%")

    plt.plot(np.array(range(0,plot_max)), 100 * reserve_array[0:plot_max] / max(reserve_array))
    plt.show()

    return

parser = argparse.ArgumentParser(
    description="Flatten a residual load curve using a battery"
)
parser.add_argument("input_path", help="Path to residual load CSV file.")
parser.add_argument("output_path", help="Path to output file.")
parser.add_argument(
    "-c",
    "--capacity",
    type=float,
    help="The battery capacity in MW; defaults to 10 percent of the volume",
)
parser.add_argument(
    "-v",
    "--volume",
    default=50000.0,
    type=float,
    help="The battery volume in MWh; defaults to 50_000",
)
parser.add_argument(
    "-w",
    "--window",
    default=72,
    type=int,
    help="The number of hours after charging when energy must be discharged; defaults to 72",
)

# Profit optimization arguments.
constraint_group = parser.add_mutually_exclusive_group()
constraint_group.add_argument(
    "--constrain",
    dest="constraints_path",
    help="Path to an optional constraint CSV",
)
constraint_group.add_argument(
    "--no-constrain",
    dest="constraints_path",
    action="store_false",
    help="Disables constraints; useful only when optimizing for profit",
)

# Gradual flattening.
gradual_group = parser.add_mutually_exclusive_group()
gradual_group.add_argument(
    "--gradual",
    action="store_true",
    help="Use an iterative process to flatten the curve gradually (this is slow)",
)
gradual_group.add_argument(
    "--price",
    dest="price_path",
    help="Path to an optional price curve; uses profit optimization instead of load flattening",
)

try:
    run(parser.parse_args())
except ArgumentError as e:
    parser.print_usage()
    print("optimize.py: error:", e)
