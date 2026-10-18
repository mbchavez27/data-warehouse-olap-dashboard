import ProductCategoryReport from './ProductCategoryReport.jsx'
import FleetWorkloadReport from './FleetWorkloadReport.jsx'
import CustomerValueReport from './CustomerValueReport.jsx'
import DemandCalendarReport from './DemandCalendarReport.jsx'
import { BoxIcon, TruckIcon, UsersIcon, CalendarIcon } from '../components/Icons.jsx'

// The four reports the group agreed on. `explore` is the home page's one-line
// summary of how each report can be read: its drill path, views and filters.
export const REPORTS = [
  {
    id: 'r1',
    name: 'Products and categories',
    icon: BoxIcon,
    question: 'Which categories and products carry the most delivered units and value, and how does that change by period, vehicle and order size?',
    explore: 'Drill from categories to their top products, by period, vehicle and order size.',
    component: ProductCategoryReport,
  },
  {
    id: 'r2',
    name: 'Fleet and rider workload',
    icon: TruckIcon,
    question: 'How is delivery volume split across couriers and vehicles, and is the work fair per rider?',
    explore: "A courier x vehicle grid that drills into a courier's vehicles and riders, and how evenly the riders share the work.",
    component: FleetWorkloadReport,
  },
  {
    id: 'r3',
    name: 'Customer value',
    icon: UsersIcon,
    question: 'How concentrated is customer value, and where are the top customers?',
    explore: "Value deciles on a Pareto chart, the customers' countries and cities, and the top customers.",
    component: CustomerValueReport,
  },
  {
    id: 'r4',
    name: 'Demand calendar',
    icon: CalendarIcon,
    question: 'How does order demand move by year, quarter, month and day, and do weekends or paydays differ?',
    explore: 'The date hierarchy rolled up in one table, the trend down to a daily calendar, the weekday pattern and the busiest days.',
    component: DemandCalendarReport,
  },
]
