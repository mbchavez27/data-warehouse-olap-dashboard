import ProductCategoryReport from './ProductCategoryReport.jsx'
import FleetWorkloadReport from './FleetWorkloadReport.jsx'
import CustomerValueReport from './CustomerValueReport.jsx'
import ComingSoon from './ComingSoon.jsx'
import { BoxIcon, TruckIcon, UsersIcon, CalendarIcon } from '../components/Icons.jsx'

// The four reports the group agreed on. R4 follows the same pattern as R1–R3:
// a component in this folder plus mock data in api/mock.js.
export const REPORTS = [
  {
    id: 'r1',
    name: 'Products and categories',
    icon: BoxIcon,
    question: 'Which categories and products carry the most delivered units and value, and how does that change by period, vehicle and order size?',
    component: ProductCategoryReport,
  },
  {
    id: 'r2',
    name: 'Fleet and rider workload',
    icon: TruckIcon,
    question: 'How is delivery volume split across couriers and vehicles, and is the work fair per rider?',
    component: FleetWorkloadReport,
  },
  {
    id: 'r3',
    name: 'Customer value',
    icon: UsersIcon,
    question: 'How concentrated is customer value, and where are the top customers?',
    component: CustomerValueReport,
  },
  {
    id: 'r4',
    name: 'Demand calendar',
    icon: CalendarIcon,
    question: 'How does order demand move by year, quarter, month and day, and do weekends or paydays differ?',
    component: ComingSoon,
  },
]
