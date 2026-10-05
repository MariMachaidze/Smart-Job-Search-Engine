import { useState } from 'react'
import { SkillsTab } from './SkillsTab'
import { DocumentsTab } from './DocumentsTab'
import { CompaniesTab } from './CompaniesTab'
import { TrackerTab } from './TrackerTab'
import { StatisticsTab } from './StatisticsTab'

const TABS = ['Skills', 'Resumes & Cover Letters', 'Companies', 'Tracker', 'Statistics'] as const
type Tab = (typeof TABS)[number]

export function ProfilePage() {
  const [activeTab, setActiveTab] = useState<Tab>('Skills')

  return (
    <div className="page">
      <h1 className="page-title">Profile</h1>
      <p className="page-subtitle">Your parsed resume, generated documents, source companies, tracker, and stats.</p>

      <div className="tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab}
            role="tab"
            type="button"
            className={`tab-button ${activeTab === tab ? 'active' : ''}`}
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'Skills' && <SkillsTab />}
      {activeTab === 'Resumes & Cover Letters' && <DocumentsTab />}
      {activeTab === 'Companies' && <CompaniesTab />}
      {activeTab === 'Tracker' && <TrackerTab />}
      {activeTab === 'Statistics' && <StatisticsTab />}
    </div>
  )
}
