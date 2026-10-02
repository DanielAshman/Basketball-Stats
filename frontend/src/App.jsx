import { NavLink, Route, Routes } from 'react-router-dom'
import VideoDashboard from './pages/VideoDashboard'
import ManualEntryPage from './pages/ManualEntryPage'


const navLinkClass = ({ isActive }) =>
  `rounded px-3 py-1.5 text-sm font-medium ${
    isActive ? 'bg-orange-600 text-white' : 'border border-neutral-300 dark:border-neutral-600'
  }`

function App() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Basketball Analytics</h1>
        <nav className="flex gap-2">
          <NavLink to="/" end className={navLinkClass}>
            Video Upload
          </NavLink>
          <NavLink to="/manual" className={navLinkClass}>
            Live Game Entry
          </NavLink>
        </nav>
      </div>

      <Routes>
        <Route path="/" element={<VideoDashboard />} />
        <Route path="/manual" element={<ManualEntryPage />} />
      </Routes>
    </div>
  )
}

export default App
