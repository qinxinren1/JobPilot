#!/usr/bin/env node
/**
 * Generate resume HTML using htmldocs template
 * 
 * Unified interface - accepts resume props directly (preferred) or profile format (legacy).
 * Usage: node generate_resume_html.js <resume_props_json> [job_position]
 * 
 * Resume props format: {name, summary, contact, experience, projects, education, skills}
 * Profile format (legacy): {personal, experience, skills_boundary, ...}
 */

const path = require('path');
const fs = require('fs');

// Get resume props data from command line
// Can accept either resume props directly or profile (for backward compatibility)
const inputJson = process.argv[2];

if (!inputJson) {
  console.error('Usage: node generate_resume_html.js <resume_props_json>');
  process.exit(1);
}

let resumeProps;
try {
  const parsed = JSON.parse(inputJson);
  
  // Check if it's already in resume props format (has 'name', 'contact', 'experience', etc.)
  if (parsed.name && parsed.contact && parsed.experience !== undefined) {
    // Already in resume props format
    resumeProps = parsed;
  } else {
    // Legacy: profile format, convert it
    const profile = parsed;
    const jobPosition = process.argv[3] || '';
    resumeProps = convertProfileToResumeProps(profile, jobPosition);
  }
} catch (e) {
  console.error('Invalid JSON:', e.message);
  process.exit(1);
}

// Get absolute paths
// Script is now in src/jobpilot/resume/scripts/
// Need to go up to project root: ../../../../ (resume/scripts -> resume -> applypilot -> src -> root)
const scriptDir = __dirname;
const projectRoot = path.join(scriptDir, '../../../../');
const templatesPath = path.join(scriptDir, 'templates');
const resumeTsxPath = path.join(templatesPath, 'Resume.tsx');
const nodeModulesPath = path.join(projectRoot, 'node_modules');

// Check if template exists
if (!fs.existsSync(resumeTsxPath)) {
  console.error(`Error: Resume template not found at ${resumeTsxPath}`);
  process.exit(1);
}

// Check if node_modules exists
if (!fs.existsSync(nodeModulesPath)) {
  console.error(`Error: node_modules not found. Please run: npm install`);
  process.exit(1);
}

// Format date from various formats to "MMM YYYY" format
function formatDate(dateString) {
  if (!dateString || dateString === 'Present') {
    return dateString || '';
  }
  
  // If already in "MMM YYYY" or "MMMM YYYY" format, return as is (but normalize to "MMM YYYY")
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const fullMonthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  
  // Check if it's already in a readable format (contains month name)
  for (let i = 0; i < fullMonthNames.length; i++) {
    if (dateString.includes(fullMonthNames[i])) {
      // Extract year and return in "MMM YYYY" format
      const yearMatch = dateString.match(/\d{4}/);
      const year = yearMatch ? yearMatch[0] : '';
      return year ? `${monthNames[i]} ${year}` : dateString;
    }
  }
  
  // Check if it's in "MMM YYYY" format already
  for (let i = 0; i < monthNames.length; i++) {
    if (dateString.includes(monthNames[i])) {
      return dateString; // Already in correct format
    }
  }
  
  // Try to parse "YYYY-MM" format
  const yyyyMmMatch = dateString.match(/^(\d{4})-(\d{1,2})/);
  if (yyyyMmMatch) {
    const year = yyyyMmMatch[1];
    const month = parseInt(yyyyMmMatch[2], 10);
    if (month >= 1 && month <= 12) {
      return `${monthNames[month - 1]} ${year}`;
    }
  }
  
  // Try to parse "YYYY/MM" format
  const yyyySlashMmMatch = dateString.match(/^(\d{4})\/(\d{1,2})/);
  if (yyyySlashMmMatch) {
    const year = yyyySlashMmMatch[1];
    const month = parseInt(yyyySlashMmMatch[2], 10);
    if (month >= 1 && month <= 12) {
      return `${monthNames[month - 1]} ${year}`;
    }
  }
  
  // Try to parse "MM/YYYY" format
  const mmSlashYyyyMatch = dateString.match(/^(\d{1,2})\/(\d{4})/);
  if (mmSlashYyyyMatch) {
    const month = parseInt(mmSlashYyyyMatch[1], 10);
    const year = mmSlashYyyyMatch[2];
    if (month >= 1 && month <= 12) {
      return `${monthNames[month - 1]} ${year}`;
    }
  }
  
  // If we can't parse it, return as is
  return dateString;
}

// Convert profile data to Resume component format
function convertProfileToResumeProps(profile, jobPosition) {
  const personal = profile.personal || {};
  const experience = profile.experience || {};
  const skillsBoundary = profile.skills_boundary || {};
  
  // Extract location
  const locationParts = [];
  if (personal.city) locationParts.push(personal.city);
  if (personal.province_state) locationParts.push(personal.province_state);
  const location = locationParts.join(', ') || '';
  
  // Extract contact info
  const linkedinUrl = personal.linkedin_url || '';
  const githubUrl = personal.github_url || '';
  const linkedinHandle = linkedinUrl.split('/').filter(Boolean).pop() || '';
  const githubHandle = githubUrl.split('/').filter(Boolean).pop() || '';
  
  // Convert experience
  const workExperiences = (experience.work_experiences || []).map(exp => ({
    company: exp.company || '',
    title: exp.title || '',
    location: exp.location || '',
    startDate: formatDate(exp.start_date || ''),
    endDate: exp.current ? 'Present' : formatDate(exp.end_date || ''),
    achievements: exp.bullets || [],
  }));
  
  // Convert projects
  const projects = (experience.projects || []).map(proj => ({
    name: proj.name || '',
    dateRange: `${formatDate(proj.start_date || '')} – ${proj.current ? 'Present' : formatDate(proj.end_date || '')}`,
    githubUrl: proj.url || '',
    achievements: proj.bullets || [],
  }));
  
  // Convert education - 支持多个教育经历，包含所有字段
  const education = (experience.education || []).map(edu => ({
    school: edu.school || '',
    degree: edu.degree || '',
    field: edu.field || '',
    location: edu.location || '',
    startDate: formatDate(edu.start_date || ''),
    endDate: formatDate(edu.end_date || ''),
    gpa: edu.gpa || '',
    honors: edu.honors || [],
  }));
  
  // Convert awards
  const awards = (experience.awards || []).map(award => ({
    name: award.name || '',
    issuer: award.issuer || '',
    date: formatDate(award.date || ''),
    description: award.description || '',
  }));
  
  // Convert skills
  const skills = {
    languages: skillsBoundary.programming_languages || [],
    frameworks: skillsBoundary.frameworks || [],
    technologies: [
      ...(skillsBoundary.databases || []),
      ...(skillsBoundary.devops || []),
      ...(skillsBoundary.tools || []),
    ],
    softSkills: [
      ...(skillsBoundary.product_strategy || skillsBoundary.productStrategy || []),
      ...(skillsBoundary.technical_literacy || skillsBoundary.technicalLiteracy || []),
      ...(skillsBoundary.data_analysis || skillsBoundary.dataAnalysis || []),
      ...(skillsBoundary.soft_skills || skillsBoundary.softSkills || []),
    ],
    // spokenLanguages: use spoken_languages, spokenLanguages, or fallback to languages (for backward compatibility)
    spokenLanguages: skillsBoundary.spoken_languages || skillsBoundary.spokenLanguages || skillsBoundary.languages || [],
  };
  
  // Generate summary (保留但不显示在模板中)
  const summaryParts = [];
  if (experience.years_of_experience_total) {
    summaryParts.push(`${experience.years_of_experience_total} years of experience`);
  }
  if (experience.current_job_title && experience.current_company) {
    summaryParts.push(`Currently ${experience.current_job_title} at ${experience.current_company}`);
  } else if (jobPosition || experience.target_role) {
    summaryParts.push(`Seeking ${jobPosition || experience.target_role} positions`);
  }
  const summary = summaryParts.length > 0
    ? summaryParts.join('. ') + '.'
    : 'Experienced professional seeking new opportunities.';
  
  return {
    name: personal.full_name || '',
    summary: summary,
    contact: {
      phone: personal.phone || '',
      email: personal.email || '',
      linkedin: linkedinHandle,
      github: githubHandle,
      location: location,
    },
    experience: workExperiences,
    projects: projects,
    education: education,
    skills: skills,
    awards: awards,
    portfolioUrl: personal.portfolio_url || '',
  };
}

// Generate HTML using htmldocs
async function generateResumeHTML() {
  try {
    // Register ts-node for TypeScript support
    try {
      require('ts-node').register({
        transpileOnly: true,
        compilerOptions: {
          module: 'commonjs',
          esModuleInterop: true,
          jsx: 'react',
          target: 'es2020',
          resolveJsonModule: true,
          skipLibCheck: true,
          baseUrl: scriptDir,
          paths: {
            '@htmldocs/react': [path.join(nodeModulesPath, '@htmldocs', 'react')],
            '@htmldocs/render': [path.join(nodeModulesPath, '@htmldocs', 'render')],
          },
        },
      });
      
      // Register tsconfig-paths if available
      try {
        const tsconfigPaths = require('tsconfig-paths');
        tsconfigPaths.register({
          baseUrl: scriptDir,
          paths: {
            '@htmldocs/react': [path.join(nodeModulesPath, '@htmldocs', 'react')],
            '@htmldocs/render': [path.join(nodeModulesPath, '@htmldocs', 'render')],
          },
        });
      } catch (e) {
        // tsconfig-paths not available, continue without it
      }
    } catch (e) {
      throw new Error(`Failed to register ts-node: ${e.message}. Please install: npm install --save-dev ts-node typescript`);
    }
    
    // Import htmldocs render from npm package
    let renderModule;
    try {
      renderModule = require('@htmldocs/render');
    } catch (e) {
      throw new Error(`Failed to load @htmldocs/render: ${e.message}. Please install: npm install --save-dev @htmldocs/render`);
    }
    
    const { renderAsync } = renderModule;
    
    // Import React
    const React = require('react');
    
    // Mock CSS imports
    const originalRequire = require;
    require = function(id) {
      if (id.endsWith('.css')) {
        return {};
      }
      return originalRequire.apply(this, arguments);
    };
    
    // Import Resume component
    const Resume = require(resumeTsxPath).default;
    
    // Restore require
    require = originalRequire;
    
    // Render component (resumeProps already in correct format)
    const html = await renderAsync(
      React.createElement(Resume, resumeProps)
    );
    
    console.log(html);
  } catch (error) {
    console.error('Error generating resume HTML:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
}

generateResumeHTML();
