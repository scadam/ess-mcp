/**
 * Sample data for ESS-MCP Widget Preview Gallery.
 *
 * SAMPLE_DATA  → injected as window.openai.toolOutput
 * SAMPLE_INPUT → injected as window.openai.toolInput
 *
 * STRING_WIDGETS use JSON.parse(toolOutput) internally,
 * so toolOutput must be a JSON string for those widgets.
 * All others expect a plain object.
 */

const STRING_WIDGETS = ["update-incident", "update-task"];

const SAMPLE_DATA = {
  "worker-profile": {
    name: "Sarah Chen",
    descriptor: "Sarah Chen",
    businessTitle: "Senior Software Engineer",
    workdayId: "WD-204851",
    workerId: "EMP-10234",
    workerType: "Regular",
    location: "San Francisco",
    locationId: "LOC-SF-001",
    country: "United States",
    countryCode: "US",
    email: "sarah.chen@company.com",
    supervisoryOrganization: "Engineering - Platform",
    jobProfile: "Software Engineer IV",
    jobType: "Full-Time",
    primaryJobDescriptor: "Senior Software Engineer",
    primaryJobId: "JP-4021"
  },

  "org-chart": {
    manager: { name: "David Park", businessTitle: "VP of Engineering", descriptor: "VP of Engineering" },
    worker: { name: "Sarah Chen", businessTitle: "Senior Software Engineer", descriptor: "Senior Software Engineer" },
    directReports: [
      { name: "Alex Rivera", businessTitle: "Software Engineer", descriptor: "Software Engineer" },
      { name: "Maya Johnson", businessTitle: "Software Engineer", descriptor: "Software Engineer" },
      { name: "James Wilson", businessTitle: "Junior Developer", descriptor: "Junior Developer" }
    ],
    organization: "Engineering - Platform"
  },

  "leave-booking": {
    eligibleAbsenceTypes: [
      { name: "Annual Leave", id: "AT001", unit: "Days" },
      { name: "Sick Leave", id: "AT002", unit: "Days" },
      { name: "Personal Leave", id: "AT003", unit: "Days" }
    ],
    leaveBalances: [
      { planName: "Annual Leave", balance: 15, unit: "Days", timeOffTypes: "Annual Leave" },
      { planName: "Sick Leave", balance: 8, unit: "Days", timeOffTypes: "Sick Leave" },
      { planName: "Personal Leave", balance: 3, unit: "Days", timeOffTypes: "Personal Leave" }
    ],
    bookedTimeOff: [
      { date: "2026-04-15", timeOffType: "Annual Leave", quantity: "8", unit: "Hours", status: "Approved" },
      { date: "2026-04-16", timeOffType: "Annual Leave", quantity: "8", unit: "Hours", status: "Approved" }
    ]
  },

  "team-calendar": {
    entries: [
      { startDate: "2026-04-06", endDate: "2026-04-10", type: "Time Off", workerName: "Alex Rivera" },
      { startDate: "2026-04-08", endDate: "2026-04-08", type: "Holiday", workerName: "Company Holiday" },
      { startDate: "2026-04-13", endDate: "2026-04-14", type: "Time Off", workerName: "Maya Johnson" },
      { startDate: "2026-04-15", endDate: "2026-04-16", type: "Time Off", workerName: "Sarah Chen" },
      { startDate: "2026-04-20", endDate: "2026-04-24", type: "Time Off", workerName: "James Wilson" }
    ]
  },

  "team-dashboard": {
    success: true,
    totalHeadcount: 12,
    byTitle: {
      "Software Engineer": 5,
      "Senior Software Engineer": 3,
      "Engineering Manager": 2,
      "DevOps Engineer": 1,
      "QA Engineer": 1
    },
    byOrganization: {
      "Platform": 5,
      "Infrastructure": 4,
      "Quality": 3
    },
    teamMembers: [
      { name: "Sarah Chen", businessTitle: "Senior Software Engineer", isManager: false, email: "sarah.chen@company.com" },
      { name: "David Park", businessTitle: "VP of Engineering", isManager: true, email: "david.park@company.com" },
      { name: "Alex Rivera", businessTitle: "Software Engineer", isManager: false, email: "alex.rivera@company.com" },
      { name: "Maya Johnson", businessTitle: "Software Engineer", isManager: false, email: "maya.johnson@company.com" },
      { name: "James Wilson", businessTitle: "Junior Developer", isManager: false, email: "james.wilson@company.com" },
      { name: "Priya Sharma", businessTitle: "DevOps Engineer", isManager: false, email: "priya.sharma@company.com" }
    ]
  },

  "change-business-title": {
    worker: {
      name: "Sarah Chen",
      currentTitle: "Software Engineer",
      businessTitle: "Software Engineer",
      proposedBusinessTitle: "Senior Software Engineer"
    }
  },

  "learning-assignments": {
    assignments: [
      { learningContentTitle: "Security Awareness Training", assignmentStatus: "In Progress", dueDate: "2026-04-30", contentProvider: "KnowBe4", required: true, overdue: false, contentURL: "#" },
      { learningContentTitle: "Leadership Fundamentals", assignmentStatus: "Not Started", dueDate: "2026-05-15", contentProvider: "LinkedIn Learning", required: false, overdue: false, contentURL: "#" },
      { learningContentTitle: "Data Privacy & GDPR", assignmentStatus: "Completed", dueDate: "2026-03-15", contentProvider: "Internal", required: true, overdue: false, contentURL: "#" },
      { learningContentTitle: "Agile Project Management", assignmentStatus: "Overdue", dueDate: "2026-03-01", contentProvider: "Coursera", required: true, overdue: true, contentURL: "#" },
      { learningContentTitle: "Cloud Architecture Basics", assignmentStatus: "In Progress", dueDate: "2026-06-01", contentProvider: "AWS Training", required: false, overdue: false, contentURL: "#" }
    ]
  },

  "learning-search": {
    skills: [
      { id: "skill_001", descriptor: "Project Management" },
      { id: "skill_002", descriptor: "Cloud Computing" },
      { id: "skill_003", descriptor: "Data Analysis" },
      { id: "skill_004", descriptor: "Leadership" },
      { id: "skill_005", descriptor: "Machine Learning" }
    ],
    topics: [
      { id: "topic_001", descriptor: "Career Development" },
      { id: "topic_002", descriptor: "Technical Skills" },
      { id: "topic_003", descriptor: "Compliance" },
      { id: "topic_004", descriptor: "Management" },
      { id: "topic_005", descriptor: "Diversity & Inclusion" }
    ]
  },

  "inbox-tasks": {
    tasks: [
      { id: "task_3001", descriptor: "Approve Time Off Request – Alex Rivera", subject: "Time Off Request", stepType: "Approval", status: "Awaiting Action", initiator: "Alex Rivera", assigned: "2026-03-28", due: "2026-04-05" },
      { id: "task_3002", descriptor: "Approve Expense Report – Maya Johnson", subject: "Expense Report", stepType: "Approval", status: "Awaiting Action", initiator: "Maya Johnson", assigned: "2026-03-29", due: "2026-04-06" },
      { id: "task_3003", descriptor: "Review Job Requisition – Engineering", subject: "Job Requisition", stepType: "To Do", status: "In Progress", initiator: "David Park", assigned: "2026-03-25", due: "2026-04-10" },
      { id: "task_3004", descriptor: "Approve Title Change – James Wilson", subject: "Title Change", stepType: "Approval", status: "Awaiting Action", initiator: "James Wilson", assigned: "2026-03-30", due: "2026-04-02" },
      { id: "task_3005", descriptor: "Complete Onboarding Checklist", subject: "Onboarding", stepType: "To Do", status: "Not Started", initiator: "HR System", assigned: "2026-04-01", due: "2026-04-15" }
    ]
  },

  "give-feedback": {
    people: [
      { descriptor: "Alex Rivera", businessTitle: "Software Engineer", workerId: "WD-204852" },
      { descriptor: "Maya Johnson", businessTitle: "Software Engineer", workerId: "WD-204853" },
      { descriptor: "James Wilson", businessTitle: "Junior Developer", workerId: "WD-204854" },
      { descriptor: "Priya Sharma", businessTitle: "DevOps Engineer", workerId: "WD-204855" },
      { descriptor: "David Park", businessTitle: "VP of Engineering", workerId: "WD-204856" }
    ],
    badges: [
      { id: "badge_001", descriptor: "Innovation Champion" },
      { id: "badge_002", descriptor: "Team Player" },
      { id: "badge_003", descriptor: "Customer Focus" },
      { id: "badge_004", descriptor: "Going Above & Beyond" },
      { id: "badge_005", descriptor: "Mentorship" }
    ]
  },

  "goals-dashboard": {
    goals: [
      { id: "goal_001", name: "Deliver Platform v2.0", description: "Ship the next major platform release with OAuth 2.0 rotation and rate limiting.", status: "On Track", percentComplete: 72, dueDate: "2026-06-30", categories: ["Engineering", "Delivery"] },
      { id: "goal_002", name: "Reduce API Latency by 40%", description: "Optimize database queries and caching layers to reduce p95 latency from 800ms to 480ms.", status: "At Risk", percentComplete: 45, dueDate: "2026-05-15", categories: ["Engineering", "Performance"] },
      { id: "goal_003", name: "Complete AWS Solutions Architect Cert", description: "Obtain the AWS Solutions Architect Professional certification.", status: "In Progress", percentComplete: 60, dueDate: "2026-07-31", categories: ["Learning", "Career Development"] },
      { id: "goal_004", name: "Mentor 2 Junior Engineers", description: "Provide structured mentorship program for two new team members.", status: "On Track", percentComplete: 50, dueDate: "2026-12-31", categories: ["Leadership", "Team"] },
      { id: "goal_005", name: "Improve Test Coverage to 85%", description: "Increase unit and integration test coverage across the platform codebase.", status: "Not Started", percentComplete: 0, dueDate: "2026-09-30", categories: ["Engineering", "Quality"] }
    ]
  },

  "create-check-in-form": {
    people: [
      { descriptor: "Alex Rivera", businessTitle: "Software Engineer", workerId: "WD-204852" },
      { descriptor: "Maya Johnson", businessTitle: "Software Engineer", workerId: "WD-204853" },
      { descriptor: "James Wilson", businessTitle: "Junior Developer", workerId: "WD-204854" },
      { descriptor: "Priya Sharma", businessTitle: "DevOps Engineer", workerId: "WD-204855" }
    ],
    topics: [
      { id: "topic_ci_001", descriptor: "Career Development" },
      { id: "topic_ci_002", descriptor: "Performance Review" },
      { id: "topic_ci_003", descriptor: "Project Updates" },
      { id: "topic_ci_004", descriptor: "Work-Life Balance" },
      { id: "topic_ci_005", descriptor: "Skills Growth" },
      { id: "topic_ci_006", descriptor: "Feedback" }
    ]
  },

  "development-items": {
    items: [
      { name: "Complete AWS Solutions Architect Certification", description: "Prepare for and pass the AWS SA Professional exam to deepen cloud architecture skills.", status: "In Progress", category: "Formal Education", relatedSkills: ["Cloud Computing", "AWS", "Architecture"], dueDate: "2026-07-31" },
      { name: "Lead Cross-Team API Design Workshop", description: "Design and facilitate a workshop on REST API best practices for the engineering department.", status: "Not Started", category: "Assignment", relatedSkills: ["API Design", "Leadership", "Communication"], dueDate: "2026-06-15" },
      { name: "Advanced Kubernetes Training", description: "Complete the CKA preparation course and hands-on labs.", status: "In Progress", category: "Training", relatedSkills: ["Kubernetes", "DevOps", "Container Orchestration"], dueDate: "2026-08-30" },
      { name: "Contribute to Open Source MCP SDK", description: "Make meaningful contributions to the MCP Python SDK open source project.", status: "Active", category: "Assignment", relatedSkills: ["Python", "Open Source", "MCP"], dueDate: "2026-09-30" },
      { name: "Data Engineering Fundamentals Course", description: "Complete the data engineering pathway covering ETL, data pipelines, and warehousing.", status: "Completed", category: "Training", relatedSkills: ["Data Engineering", "SQL", "ETL"], completionDate: "2026-03-15" }
    ]
  },

  "team-goals": {
    team: [
      { descriptor: "Alex Rivera", businessTitle: "Software Engineer", goals: [
        { name: "Implement Rate Limiting", status: "On Track", percentComplete: 80, dueDate: "2026-05-30", description: "Add rate limiting to all public API endpoints." },
        { name: "Reduce Bug Backlog by 50%", status: "At Risk", percentComplete: 35, dueDate: "2026-06-30", description: "Triage and resolve high-priority bugs in the backlog." }
      ]},
      { descriptor: "Maya Johnson", businessTitle: "Software Engineer", goals: [
        { name: "Lead Frontend Redesign", status: "On Track", percentComplete: 65, dueDate: "2026-07-15", description: "Redesign the dashboard UI with accessibility improvements." },
        { name: "Improve Lighthouse Score to 95+", status: "On Track", percentComplete: 70, dueDate: "2026-06-30", description: "Optimize performance, accessibility, and SEO metrics." },
        { name: "Mentor Intern on React", status: "In Progress", percentComplete: 40, dueDate: "2026-08-31", description: "Provide weekly mentorship sessions on React patterns." }
      ]},
      { descriptor: "James Wilson", businessTitle: "Junior Developer", goals: [
        { name: "Complete Onboarding Milestones", status: "On Track", percentComplete: 90, dueDate: "2026-04-30", description: "Finish all onboarding tasks and first contribution." },
        { name: "Learn CI/CD Pipeline", status: "Behind", percentComplete: 20, dueDate: "2026-05-15", description: "Understand and document the team's CI/CD pipeline." }
      ]},
      { descriptor: "Priya Sharma", businessTitle: "DevOps Engineer", goals: [
        { name: "Migrate to Kubernetes 1.30", status: "On Track", percentComplete: 55, dueDate: "2026-06-30", description: "Upgrade all production clusters to Kubernetes 1.30." },
        { name: "Implement Zero-Downtime Deployments", status: "Not Started", percentComplete: 0, dueDate: "2026-08-31", description: "Set up blue-green deployments across all services." }
      ]}
    ]
  },

  "incident-list": {
    incidents: [
      { number: "INC0012345", short_description: "Email service intermittent outage", state: "In Progress", priority: 2, category: "software", assigned_to: "Sarah Chen", opened_at: "2026-03-28T09:15:00Z", sys_id: "abc123" },
      { number: "INC0012346", short_description: "VPN connection drops frequently", state: "New", priority: 3, category: "network", assigned_to: "Alex Rivera", opened_at: "2026-03-29T14:22:00Z", sys_id: "abc124" },
      { number: "INC0012347", short_description: "Database query timeout on reports", state: "On Hold", priority: 1, category: "database", assigned_to: "James Wilson", opened_at: "2026-03-25T08:00:00Z", sys_id: "abc125" },
      { number: "INC0012348", short_description: "Printer not responding on 3rd floor", state: "Resolved", priority: 4, category: "hardware", assigned_to: "Maya Johnson", opened_at: "2026-03-20T11:45:00Z", resolved_at: "2026-03-21T09:30:00Z", sys_id: "abc126" },
      { number: "INC0012349", short_description: "SSO login failure for external users", state: "In Progress", priority: 2, category: "software", assigned_to: "Priya Sharma", opened_at: "2026-03-30T16:00:00Z", sys_id: "abc127" }
    ]
  },

  "create-incident": {},

  "update-incident": {
    incident: {
      number: "INC0012345",
      state: "In Progress",
      priority: "2 - High",
      category: "software",
      assigned_to: "Sarah Chen",
      short_description: "Email service intermittent outage",
      description: "Users reporting email service dropping connections intermittently since Monday morning. Affects Outlook and mobile clients."
    },
    link: "https://instance.service-now.com/incident.do?sys_id=abc123"
  },

  "team-incidents": {
    success: true,
    total_open: 23,
    by_priority: { "1 - Critical": 2, "2 - High": 7, "3 - Medium": 10, "4 - Low": 4 },
    by_assignee: { "Sarah Chen": 5, "Alex Rivera": 6, "Maya Johnson": 4, "James Wilson": 3, "Priya Sharma": 5 },
    recent_incidents: [
      { number: "INC0012345", short_description: "Email service intermittent outage", priority: 2, assigned_to: "Sarah Chen", state: "In Progress" },
      { number: "INC0012349", short_description: "SSO login failure for external users", priority: 2, assigned_to: "Priya Sharma", state: "In Progress" },
      { number: "INC0012347", short_description: "Database query timeout on reports", priority: 1, assigned_to: "James Wilson", state: "On Hold" },
      { number: "INC0012350", short_description: "Cloud storage sync delay", priority: 3, assigned_to: "Alex Rivera", state: "New" }
    ]
  },

  "approval-review": {
    review: {
      nonce: "demo-nonce-001",
      provider: "ServiceNow",
      approvalId: "APRV-5501",
      expiresAt: "2026-04-15T23:59:59Z",
      item: {
        title: "Laptop Upgrade Request - MacBook Pro 16\"",
        status: "Pending Approval",
        summary: "Request for MacBook Pro 16\" M4 Max with 64GB RAM for development workstation upgrade. Current machine is 4 years old and experiencing performance issues during compilation."
      }
    }
  },

  "task-list": {
    approvalCount: 3,
    taskCount: 5,
    items: [
      { id: "TASK001", kind: "approval", system: "servicenow", title: "Approve: Software License - Adobe Creative Cloud", status: "Pending", priority: "2", assignee: "Sarah Chen", dueDate: "2026-04-05", createdDate: "2026-03-28", summary: "Annual renewal of Adobe CC licenses for Design team" },
      { id: "TASK002", kind: "task", system: "servicenow", title: "Update firewall rules for new microservice", status: "Open", priority: "1", assignee: "Sarah Chen", dueDate: "2026-04-03", createdDate: "2026-03-27", summary: "Configure ingress rules for the new payment gateway", number: "STSK0018234" },
      { id: "TASK003", kind: "approval", system: "servicenow", title: "Approve: Change Request - Database Migration", status: "Pending", priority: "2", assignee: "Sarah Chen", dueDate: "2026-04-06", createdDate: "2026-03-29", summary: "Migration of user DB from PostgreSQL 14 to 16" },
      { id: "TASK004", kind: "task", system: "servicenow", title: "Investigate slow API response times", status: "In Progress", priority: "2", assignee: "Sarah Chen", dueDate: "2026-04-08", createdDate: "2026-03-25", summary: "Trace and resolve latency spikes in /api/orders endpoint", number: "STSK0018240" },
      { id: "TASK005", kind: "approval", system: "servicenow", title: "Approve: New Hire Equipment - Engineering", status: "Pending", priority: "3", assignee: "Sarah Chen", dueDate: "2026-04-10", createdDate: "2026-03-30", summary: "Standard dev workstation setup for 2 new engineering hires" },
      { id: "TASK006", kind: "task", system: "servicenow", title: "Deploy monitoring dashboards for Q2", status: "Open", priority: "3", assignee: "Sarah Chen", dueDate: "2026-04-12", createdDate: "2026-03-31", summary: "Set up Grafana dashboards for new microservices", number: "STSK0018250" },
      { id: "TASK007", kind: "task", system: "servicenow", title: "Review security scan results", status: "Open", priority: "1", assignee: "Sarah Chen", dueDate: "2026-04-04", createdDate: "2026-03-26", summary: "Triage and remediate findings from Q1 vulnerability scan", number: "STSK0018255" }
    ]
  },

  "update-task": {
    task: {
      task_id: "STSK0018234",
      subject: "Update firewall rules for new microservice",
      status: "Open",
      priority: "1 - High",
      description: "Configure ingress rules for the new payment gateway service. Allow traffic from load balancer on ports 8443 and 9090.",
      assigned_to: "Sarah Chen",
      number: "STSK0018234"
    }
  },

  "cart-summary": {
    items: [
      { name: "MacBook Pro 16\" M4 Max", quantity: 1, price: 3499.00, subtotal: 3499.00, cart_item_id: "CI001" },
      { name: "Dell 27\" 4K Monitor", quantity: 2, price: 449.99, subtotal: 899.98, cart_item_id: "CI002" },
      { name: "Logitech MX Keys Keyboard", quantity: 1, price: 99.99, subtotal: 99.99, cart_item_id: "CI003" }
    ],
    total_items: 4,
    subtotal: 4498.97
  },

  "catalog-list": {
    items: [
      { sys_id: "CAT001", name: "MacBook Pro 16\"", short_description: "Apple M4 Max, 64GB RAM, 1TB SSD", category: "Laptops", price: "$3,499.00" },
      { sys_id: "CAT002", name: "Dell XPS 15", short_description: "Intel i9, 32GB RAM, 512GB SSD", category: "Laptops", price: "$1,899.00" },
      { sys_id: "CAT003", name: "Dell 27\" 4K Monitor", short_description: "UltraSharp 27\" 4K USB-C Hub Monitor", category: "Monitors", price: "$449.99" },
      { sys_id: "CAT004", name: "Logitech MX Keys", short_description: "Advanced wireless keyboard with backlight", category: "Accessories", price: "$99.99" },
      { sys_id: "CAT005", name: "Sony WH-1000XM5", short_description: "Noise cancelling wireless headphones", category: "Accessories", price: "$349.99" },
      { sys_id: "CAT006", name: "Standing Desk", short_description: "Electric height-adjustable desk, 60x30", category: "Furniture", price: "$599.00" }
    ]
  },

  "catalog-item": {
    sys_id: "CAT001",
    name: "MacBook Pro 16\"",
    short_description: "Apple M4 Max, 64GB RAM, 1TB SSD",
    description: "Apple M4 Max processor with 64GB unified memory and 1TB SSD storage. Includes 16-inch Liquid Retina XDR display.",
    price: "$3,499.00",
    category: "Laptops",
    delivery_time: "5-7 Business Days",
    variables: [
      { name: "configuration", label: "Configuration", type: "select", mandatory: true, choices: [{ label: "Standard", value: "standard" }, { label: "Custom", value: "custom" }], active: true, id: "v1" },
      { name: "justification", label: "Justification", type: "text", mandatory: true, active: true, id: "v2" },
      { name: "needed_by", label: "Needed By", type: "date", mandatory: false, active: true, id: "v3" }
    ]
  },

  "create-change-request": {},
  "create-problem": {},

  "crm-pipeline": {
    stages: [
      { stage: "Prospecting", count: 8, amount: 120000 },
      { stage: "Qualification", count: 12, amount: 340000 },
      { stage: "Proposal", count: 6, amount: 520000 },
      { stage: "Negotiation", count: 4, amount: 380000 },
      { stage: "Closed Won", count: 3, amount: 290000 }
    ],
    opportunities: [
      { name: "Acme Corp - Enterprise Suite", stage_name: "Negotiation", amount: 175000 },
      { name: "TechStart Inc - Cloud Migration", stage_name: "Proposal", amount: 95000 },
      { name: "Global Retail - POS Upgrade", stage_name: "Qualification", amount: 68000 },
      { name: "FinServ Partners - Analytics Platform", stage_name: "Proposal", amount: 220000 },
      { name: "MedTech Solutions - Compliance Suite", stage_name: "Prospecting", amount: 45000 }
    ],
    totals: {
      opportunities: 33,
      pipeline_amount: 1650000,
      weighted_pipeline_amount: 825000
    }
  },

  "crm-account-360": {
    account: {
      name: "Acme Corporation",
      industry: "Technology",
      type: "Enterprise",
      phone: "+1 (415) 555-0100",
      billing_city: "San Francisco",
      billing_country: "United States"
    },
    summary: {
      contacts: 8,
      opportunities: 5,
      open_opportunities: 3,
      open_pipeline_amount: 475000,
      cases: 2
    },
    contacts: [
      { name: "John Mitchell", title: "CTO", email: "john.mitchell@acme.com" },
      { name: "Lisa Wang", title: "VP Engineering", email: "lisa.wang@acme.com" },
      { name: "Robert Garcia", title: "Procurement Manager", email: "robert.garcia@acme.com" }
    ],
    opportunities: [
      { name: "Enterprise Suite Renewal", stage_name: "Negotiation", amount: 175000, close_date: "2026-05-15" },
      { name: "Cloud Migration Phase 2", stage_name: "Proposal", amount: 200000, close_date: "2026-06-30" },
      { name: "Security Add-on", stage_name: "Qualification", amount: 100000, close_date: "2026-07-15" }
    ],
    events: [
      { subject: "Q2 Business Review", start_datetime: "2026-04-10T14:00:00Z", activity_date: "2026-04-10" },
      { subject: "Technical Demo - Cloud Platform", start_datetime: "2026-04-15T10:00:00Z", activity_date: "2026-04-15" }
    ],
    tasks: [
      { subject: "Send updated proposal", status: "Open", priority: "High" },
      { subject: "Schedule executive sponsor call", status: "Open", priority: "Normal" }
    ],
    cases: [
      { case_number: "CS-4421", subject: "API rate limiting issue", status: "Open", priority: "High" },
      { case_number: "CS-4398", subject: "SSO configuration support", status: "Closed", priority: "Medium" }
    ]
  },

  "crm-opportunity": {
    opportunity: {
      id: "OPP-0012345",
      name: "Acme Corp - Enterprise Suite",
      stage_name: "Negotiation",
      amount: 175000,
      close_date: "2026-05-15",
      account_name: "Acme Corporation",
      account_id: "ACC001",
      description: "Enterprise software suite annual renewal with expansion to Asia-Pacific region."
    }
  },

  "crm-lead": {
    lead: {
      id: "LEAD-5501",
      first_name: "Emily",
      last_name: "Torres",
      company: "DataFlow Systems",
      title: "Director of IT",
      email: "emily.torres@dataflow.com",
      phone: "+1 (650) 555-0182",
      lead_source: "Web",
      status: "Working",
      description: "Interested in enterprise data pipeline solutions. Met at CloudConf 2026."
    }
  },

  "lead-pipeline": {
    leads: [
      { name: "Emily Torres", company: "DataFlow Systems", status: "Working", lead_source: "Web" },
      { name: "Marcus Lee", company: "FinTech Global", status: "New", lead_source: "Referral" },
      { name: "Aisha Patel", company: "HealthCore Inc", status: "Nurturing", lead_source: "Conference" },
      { name: "Carlos Mendez", company: "RetailMax", status: "Qualified", lead_source: "Partner" },
      { name: "Jennifer Wu", company: "EduTech Pro", status: "New", lead_source: "Web" },
      { name: "Thomas Brown", company: "ManufactPro", status: "Working", lead_source: "Campaign" },
      { name: "Sophia Kim", company: "GreenEnergy Co", status: "Qualified", lead_source: "Referral" }
    ]
  },

  "team-pipeline": {
    success: true,
    teamTotals: {
      totalAmount: 2850000,
      totalWeightedAmount: 1425000,
      totalCount: 45,
      avgDealSize: 63333
    },
    byOwner: [
      { ownerName: "Sarah Chen", totalAmount: 680000, count: 12, byStage: { "Prospecting": 3, "Qualification": 4, "Proposal": 3, "Negotiation": 2 } },
      { ownerName: "Alex Rivera", totalAmount: 520000, count: 10, byStage: { "Prospecting": 2, "Qualification": 3, "Proposal": 2, "Negotiation": 3 } },
      { ownerName: "Maya Johnson", totalAmount: 450000, count: 8, byStage: { "Prospecting": 1, "Qualification": 3, "Proposal": 2, "Negotiation": 2 } },
      { ownerName: "James Wilson", totalAmount: 380000, count: 7, byStage: { "Prospecting": 2, "Qualification": 2, "Proposal": 1, "Negotiation": 2 } },
      { ownerName: "Priya Sharma", totalAmount: 820000, count: 8, byStage: { "Prospecting": 1, "Qualification": 2, "Proposal": 3, "Negotiation": 2 } }
    ]
  },

  "crm-event": {
    events: [
      { id: "EVT001", subject: "Q2 Business Review", start_datetime: "2026-04-10T14:00:00Z", end_datetime: "2026-04-10T15:00:00Z", account_name: "Acme Corporation", contact_name: "John Mitchell", location: "Conference Room A" },
      { id: "EVT002", subject: "Technical Demo - Cloud Platform", start_datetime: "2026-04-15T10:00:00Z", end_datetime: "2026-04-15T11:30:00Z", account_name: "TechStart Inc", contact_name: "Lisa Wang", location: "Virtual - Zoom" },
      { id: "EVT003", subject: "Contract Negotiation", start_datetime: "2026-04-18T09:00:00Z", end_datetime: "2026-04-18T10:00:00Z", account_name: "Global Retail", contact_name: "Robert Garcia", location: "Client Office" }
    ]
  },

  "crm-quote": {
    quotes: [
      { id: "QT-1001", quote_name: "Acme Enterprise Suite - Q2 2026", opportunity_name: "Acme Corp - Enterprise Suite", status: "Draft", expiration_date: "2026-05-01", total_price: 175000, grand_total: 175000 },
      { id: "QT-1002", quote_name: "TechStart Cloud Migration", opportunity_name: "TechStart Inc - Cloud Migration", status: "Presented", expiration_date: "2026-04-20", total_price: 95000, grand_total: 95000 },
      { id: "QT-1003", quote_name: "Global Retail POS Package", opportunity_name: "Global Retail - POS Upgrade", status: "Accepted", expiration_date: "2026-04-15", total_price: 68000, grand_total: 68000 }
    ]
  },

  "compliance-case": {
    case: {
      id: "CC-2201",
      case_number: "CC-2201",
      subject: "GDPR Data Subject Access Request",
      compliance_type: "Data Privacy",
      type: "Data Privacy",
      priority: "High",
      status: "Under Review",
      description: "Customer has submitted a DSAR requesting all personal data held. Need to compile data from CRM, billing, and support systems."
    }
  },

  "jira-issue": {
    issue: {
      key: "PLAT-1234",
      summary: "Implement OAuth 2.0 refresh token rotation",
      status: "In Progress",
      statusCategory: "in_progress",
      priority: "High",
      issue_type: "Story",
      assignee: "Sarah Chen",
      reporter: "David Park",
      description: "Implement automatic refresh token rotation as per security audit recommendation. Tokens should be rotated on each use with a grace period of 60 seconds.",
      project: "Platform",
      project_key: "PLAT",
      labels: ["security", "auth"],
      created: "2026-03-15T10:00:00Z",
      updated: "2026-04-01T14:30:00Z",
      comments: [
        { author: "David Park", body: "This is a P1 for the security team. Please prioritize.", created: "2026-03-15T10:05:00Z" },
        { author: "Sarah Chen", body: "Started implementation. PR incoming by end of week.", created: "2026-03-28T09:00:00Z" }
      ]
    }
  },

  "sprint-board": {
    sprint_name: "Platform Sprint 12",
    issues: [
      { key: "PLAT-1234", summary: "Implement OAuth 2.0 refresh token rotation", status_category: "in_progress", issue_type: "Story", priority: "High", assignee: "Sarah Chen" },
      { key: "PLAT-1235", summary: "Add rate limiting to public API endpoints", status_category: "todo", issue_type: "Story", priority: "High", assignee: "Alex Rivera" },
      { key: "PLAT-1236", summary: "Fix memory leak in WebSocket handler", status_category: "done", issue_type: "Bug", priority: "Highest", assignee: "Maya Johnson" },
      { key: "PLAT-1237", summary: "Update dependency versions for Q2", status_category: "in_progress", issue_type: "Task", priority: "Medium", assignee: "James Wilson" },
      { key: "PLAT-1238", summary: "Design API versioning strategy", status_category: "todo", issue_type: "Story", priority: "Medium", assignee: "Sarah Chen" },
      { key: "PLAT-1239", summary: "Write integration tests for payment module", status_category: "done", issue_type: "Task", priority: "Medium", assignee: "Priya Sharma" },
      { key: "PLAT-1240", summary: "Configure alerting for SLO violations", status_category: "todo", issue_type: "Task", priority: "Low", assignee: "Alex Rivera" },
      { key: "PLAT-1241", summary: "Database connection pool exhaustion", status_category: "in_progress", issue_type: "Bug", priority: "High", assignee: "James Wilson" }
    ]
  },

  "create-issue-jira": {},
  "create-project": {},

  "team-sprint-health": {
    success: true,
    totalUnresolved: 18,
    unassignedCount: 2,
    byAssignee: [
      { assignee: "Sarah Chen", total: 5, overloaded: false, byStatusCategory: { "todo": 1, "in_progress": 2, "done": 2 }, byPriority: { "High": 2, "Medium": 2, "Low": 1 } },
      { assignee: "Alex Rivera", total: 4, overloaded: false, byStatusCategory: { "todo": 2, "in_progress": 1, "done": 1 }, byPriority: { "High": 1, "Medium": 2, "Low": 1 } },
      { assignee: "Maya Johnson", total: 3, overloaded: false, byStatusCategory: { "todo": 0, "in_progress": 1, "done": 2 }, byPriority: { "Highest": 1, "Medium": 1, "Low": 1 } },
      { assignee: "James Wilson", total: 4, overloaded: true, byStatusCategory: { "todo": 1, "in_progress": 2, "done": 1 }, byPriority: { "High": 2, "Medium": 1, "Low": 1 } },
      { assignee: "Priya Sharma", total: 2, overloaded: false, byStatusCategory: { "todo": 0, "in_progress": 0, "done": 2 }, byPriority: { "Medium": 1, "Low": 1 } }
    ]
  }
};

const SAMPLE_INPUT = {
  "create-incident": {
    caller: "Sarah Chen",
    short_description: "Laptop not connecting to corporate WiFi",
    category: "network",
    urgency: "2",
    impact: "3"
  },
  "create-change-request": {},
  "create-problem": {},
  "create-issue-jira": {},
  "create-project": {},
  "crm-opportunity": {
    name: "Acme Corp - Enterprise Suite",
    stage_name: "Negotiation",
    amount: "175000",
    close_date: "2026-05-15"
  }
};
