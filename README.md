P2P Optimization
================

**optimize.py** receives a residual load curve and, using a battery, attempts to flatten the curve as much as possible.

Two arguments are required:

1. A path to a file containing the residual load.
2. A path to an output file, where results will be written.

For example:

```sh
python optimize.py load.csv tmp/out.csv
```

The output file will contain entries for each hour:

* `index` - The hour number; starts at 0.
* `residual_load` - The original residual load.
* `adjusted_load` - The adjusted load after the battery has charged or discharged.
* `charge` - The amount of energy the battery charged (positive) or discharged (negative) in MW.
* `soc` - The amount of energy stored in the battery in MWh.
* `price` - The price of energy. Only included when optimizing for profit.

Run the script with `-h` or `--help` for information on its arguments.

## Setup

### With Pipenv:

```sh
pipenv install
```

When using Pipenv, use optimize.py with `pipenv run python optimize.py ...`

### Without Pipenv:

Install Numpy:

```sh
pip install numpy
```

## Customizing the battery specifications

The default battery has a volume of 50,000 MW (50 GW). This may be changed with the `--volume` or `-v` argument:

```sh
# Use a battery of  500 MW
python optimize.py --volume 500 load.csv tmp/out.csv

# Use a battery of 10,000 MW (10 GW)
python optimize.py --volume 10000 load.csv tmp/out.csv
```

The battery will always have a capacity one-tenth of the volume: a battery of 50 GW volume will have 5 GW capacity. Change this with the `--capacity` or `-c` argument:

```sh
# Battery defaults to volume / 10 (5,000 MW)
python optimize.py load.csv tmp/out.csv

# Use a custom capacity of 2,500 MW
python optimize.py --capacity 2500 load.csv tmp/out.csv
```

Both `--volume` and `--capacity` may be used together.

```sh
# Use a volume of 20,000 MW and capacity of 2,500 MW
python optimize.py --capacity 2500 --volume 20000 load.csv tmp/out.csv
```

## Constraints

When performing load flattening, the script calculates the 72-hour moving average for each hour in the load curve and attempts to move the load towards that mean.

You may specify a custom constraint curve with the `--constrain` option. This CSV file should contain values in MW where negative values allow the battery to charge up to that capacity, and positive values allow it to discharge. The battery may not charge and discharge in the same hour.

For example:

```sh
head constraint.csv
# 2100.0    # => charge up to 2100 GW
# 1200.0    # => charge up to 1200 GW
# 200.0     # => charge up to 200 MW
# -800.0    # => discharge up to 800 MW
# -1800.0   # => discharge up to 1800 MW
# -2600.0   # => discharge up to 2600 MW
# ...

python optimize.py --constrain constraint.csv load.csv tmp/out.csv
```

## Gradual load flattening

The `--gradual` option adds a step when load flattening. The assignment of energy is normally limited by the battery capacity and the constraint curve but may be further limited by the difference between the load in the minimum and maximum hour.

For example, if the load in the peak hour is 10 GW, and the load in the trough is 6 GW, with a charging/discharging constraint of 2 GW, the algorithm would assign a 2 GW charge and 2 GW discharge in the min and max hours respectively.

With gradual flattening, the script calculates the difference between the two loads (4 GW) and assigns only 5% of this (0.2 GW) and then adds the maximum hour back into the list of candidates for optimization, perhaps to be visited again in a future iteration.

This gives hours around the ultimate peak the opportunity to also be flattened. Without gradual flattening, relatively small batteries are ineffective at peak shaving, and will often use all their volume on a single hour.

This option significantly increases the calculation time, and cannot be used when optimizing for profit.

## Optimizing for profit

Instead of flattening a residual load curve, you may seek to maximize the profit of the battery; charging in the hours when energy is cheapest, and discharging when it is most expensive. This is accomplished by providing a price curve with the `--price` argument.

```sh
head price.csv
# 24.52
# 24.52
# 29.96
# 32.68
# ...

python optimize.py --price price.csv load.csv tmp/out.csv
```

## Customizing the window (look behind) period

The algorithm works by finding the hour with the largest peak - where the battery will discharge - and searches for the hour with the lowest trough - where the battery will charge. By default, the trough must occur within 72-hours prior to the peak (the "window").

This has the effect that whenever the battery charges, it must discharge for the same amount within the window period.

Smaller windows result in faster calculations and work well for small batteries. Higher periods will allow large batteries to be more effective but increase calculation time.

## Example files

The repository contains a couple of example files:

* `constraint.csv` - A sinusoidal curve which serves as an example of a capacity constraint.
* `load.csv` - A residual load curve from a default NL 2050 scenario.
* `load.iinat.csv` - A residual load curve from the II3050 National Governance scenario.
* `price.csv` - A price curve from a default NL 2050 scenario.
* `price.iinat.csv` - A price from the the II3050 National Governance scenario.
