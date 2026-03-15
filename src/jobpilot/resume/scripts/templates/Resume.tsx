import React from "react";
import { Document, Head, Page, Spacer } from "@htmldocs/react";
import { FaPhone, FaEnvelope, FaGithub, FaLinkedin, FaMapMarkerAlt } from "react-icons/fa";

interface Education {
  school: string;
  degree: string;
  field: string;
  location: string;
  startDate: string;
  endDate: string;
  gpa: string;
  honors: string[];
}

interface Experience {
  company: string;
  title: string;
  location: string;
  startDate: string;
  endDate: string;
  achievements: string[];
}

interface Project {
  name: string;
  dateRange: string;
  githubUrl: string;
  achievements: string[];
}

interface Award {
  name: string;
  category?: string;
  issuer?: string;
  date?: string;
  description?: string;
}

interface Skills {
  languages: string[];
  frameworks: string[];
  technologies: string[];
  softSkills?: string[];
  spokenLanguages?: string[];
}

interface Contact {
  phone: string;
  email: string;
  linkedin: string;
  github: string;
  location: string;
}

export interface ResumeProps {
  name: string;
  summary?: string;  // Optional: removed from tailored resumes
  contact: Contact;
  experience: Experience[];
  projects: Project[];
  education: Education[];
  skills: Skills;
  awards?: Award[];
  portfolioUrl?: string;
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ borderBottom: "1px solid black", marginBottom: "6px", paddingBottom: "2px" }}>
      <h2 style={{ 
        fontSize: "12px", 
        fontWeight: "bold", 
        textTransform: "uppercase",
        letterSpacing: "0.5px",
        margin: 0,
        lineHeight: "1.2"
      }}>
        {children}
      </h2>
    </div>
  );
}

function Resume({
  name,
  summary,
  contact,
  experience,
  projects,
  education,
  skills,
  awards,
  portfolioUrl,
}: ResumeProps) {
  return (
    <Document size="A4" orientation="portrait">
      <Head>
        <link href="https://fonts.cdnfonts.com/css/cmu-serif" rel="stylesheet" />
      </Head>
      <Page style={{ 
        fontSize: "12px", 
        display: "flex", 
        flexDirection: "column", 
        fontFamily: "CMU Serif",
        lineHeight: "1.2",
        padding: "20px 20px 10px 20px"
      }}>
        <div style={{ marginBottom: "12px" }}>
          <div style={{ 
            display: "flex", 
            justifyContent: "space-between", 
            alignItems: "center",
            marginBottom: "6px"
          }}>
            <h1 style={{ 
              fontSize: "22px", 
              fontWeight: 600, 
              margin: 0,
              lineHeight: "1.2"
            }}>
              {name}
            </h1>
            {contact.location && (
              <div style={{ display: "flex", alignItems: "center", fontSize: "11px" }}>
                <span style={{ width: "11px", height: "11px", marginRight: "4px", flexShrink: 0, display: "inline-flex" }}>
                  <FaMapMarkerAlt size={11} />
                </span>
                {contact.location}
              </div>
            )}
          </div>
          <div style={{ 
            display: "flex", 
            justifyContent: "space-between", 
            fontSize: "11px",
            lineHeight: "1.3"
          }}>
            <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
              {contact.email && (
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span style={{ width: "11px", height: "11px", marginRight: "4px", flexShrink: 0, display: "inline-flex" }}>
                    <FaEnvelope size={11} />
                  </span>
                  <a href={`mailto:${contact.email}`} style={{ color: "inherit", textDecoration: "none" }}>
                    {contact.email}
                  </a>
                </div>
              )}
              {contact.linkedin && (
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span style={{ width: "11px", height: "11px", marginRight: "4px", flexShrink: 0, display: "inline-flex" }}>
                    <FaLinkedin size={11} />
                  </span>
                  <a href={`https://linkedin.com/in/${contact.linkedin}`} style={{ color: "inherit", textDecoration: "none" }}>
                    linkedin.com/{contact.linkedin}
                  </a>
                </div>
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "2px", alignItems: "flex-end" }}>
              {contact.phone && (
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span style={{ width: "11px", height: "11px", marginRight: "4px", flexShrink: 0, display: "inline-flex" }}>
                    <FaPhone size={11} />
                  </span>
                  {contact.phone}
                </div>
              )}
              {contact.github && (
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span style={{ width: "11px", height: "11px", marginRight: "4px", flexShrink: 0, display: "inline-flex" }}>
                    <FaGithub size={11} />
                  </span>
                  <a href={`https://github.com/${contact.github}`} style={{ color: "inherit", textDecoration: "none" }}>
                    github.com/{contact.github}
                  </a>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* EDUCATION */}
        {education.length > 0 && (
          <section style={{ marginBottom: "8px" }}>
            <SectionHeader children={undefined}>Education</SectionHeader>
            {education.map((edu, index) => (
              <div key={index} style={{ marginBottom: index < education.length - 1 ? "4px" : "0" }}>
                <div style={{ 
                  display: "flex", 
                  justifyContent: "space-between", 
                  marginBottom: "2px",
                  lineHeight: "1.2"
                }}>
                  <span style={{ fontWeight: 600 }}>{edu.school}</span>
                  <span>
                    {edu.startDate} – {edu.endDate}
                  </span>
                </div>
                <div style={{ 
                  display: "flex", 
                  justifyContent: "space-between",
                  marginBottom: "2px",
                  lineHeight: "1.2"
                }}>
                  <span style={{ fontStyle: "italic" }}>
                    {edu.degree}{edu.field ? `, ${edu.field}` : ''}
                  </span>
                  <span style={{ fontStyle: "italic" }}>
                    {[edu.location, edu.gpa ? `GPA: ${edu.gpa}` : ''].filter(Boolean).join(', ')}
                  </span>
                </div>
                {edu.honors && edu.honors.length > 0 && (
                  <div style={{ 
                    fontSize: "12px",
                    lineHeight: "1.2",
                    marginTop: "1px"
                  }}>
                    {edu.honors.join(", ")}
                  </div>
                )}
              </div>
            ))}
          </section>
        )}

        {/* WORK EXPERIENCE */}
        {experience.length > 0 && (
          <section style={{ marginBottom: "8px" }}>
            <SectionHeader children={undefined}>Work Experience</SectionHeader>
            {experience.map((job, index) => (
              <div key={index} style={{ marginBottom: index < experience.length - 1 ? "4px" : "0" }}>
                <div style={{ 
                  display: "flex", 
                  justifyContent: "space-between", 
                  marginBottom: "1px",
                  lineHeight: "1.2"
                }}>
                  <span style={{ fontWeight: 600, fontSize: "14px" }}>{job.company}</span>
                  <span>
                    {job.startDate} – {job.endDate}
                  </span>
                </div>
                <div style={{ 
                  display: "flex", 
                  justifyContent: "space-between", 
                  marginBottom: "3px",
                  lineHeight: "1.2"
                }}>
                  <span style={{ fontStyle: "italic" }}>{job.title}</span>
                  <span style={{ fontStyle: "italic" }}>{job.location}</span>
                </div>
                <ul style={{ 
                  listStyleType: "circle", 
                  marginLeft: "18px", 
                  marginTop: "1px",
                  marginBottom: "0",
                  paddingLeft: "0",
                  lineHeight: "1.3"
                }}>
                  {job.achievements.map((achievement, i) => {
                    const colonIndex = achievement.indexOf(':');
                    const hasCategory = colonIndex > 0;
                    const category = hasCategory ? achievement.substring(0, colonIndex).trim() : '';
                    const detail = hasCategory ? achievement.substring(colonIndex + 1).trim() : achievement;
                    
                    return (
                      <li key={i} style={{ 
                        marginTop: "1px", 
                        paddingLeft: "2px",
                        fontSize: "12px",
                        lineHeight: "1.3"
                      }}>
                        {hasCategory ? (
                          <>
                            <span style={{ fontWeight: "bold" }}>{category}:</span> {detail}
                          </>
                        ) : (
                          achievement
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </section>
        )}

        {/* PROJECTS */}
        {projects.length > 0 && (
          <section style={{ marginBottom: "8px" }}>
            <div style={{ 
              display: "flex", 
              alignItems: "center",
              gap: "8px",
              borderBottom: "1px solid black", 
              marginBottom: "6px", 
              paddingBottom: "2px" 
            }}>
              <h2 style={{ 
                fontSize: "12px", 
                fontWeight: "bold", 
                textTransform: "uppercase",
                letterSpacing: "0.5px",
                margin: 0,
                lineHeight: "1.2"
              }}>
                Projects
              </h2>
              {portfolioUrl && (
                <a 
                  href={portfolioUrl} 
                  style={{ 
                    fontSize: "10px",
                    color: "#0066cc",
                    textDecoration: "underline",
                    fontWeight: "normal"
                  }}
                >
                  View more on my Portfolio →
                </a>
              )}
            </div>
            {projects.map((project, index) => (
              <div key={index} style={{ marginBottom: "4px" }}>
                <div style={{ 
                  display: "flex", 
                  justifyContent: "space-between", 
                  marginBottom: "1px",
                  lineHeight: "1.2"
                }}>
                  <span style={{ fontWeight: 600, fontSize: "14px" }}>{project.name}</span>
                  <span>{project.dateRange}</span>
                </div>
                {project.githubUrl && (
                  <div style={{ marginBottom: "3px", lineHeight: "1.2" }}>
                    <a href={project.githubUrl} style={{ 
                      color: "inherit", 
                      textDecoration: "none", 
                      display: "flex", 
                      alignItems: "center",
                      fontSize: "11px"
                    }}>
                      <span style={{ width: "11px", height: "11px", marginRight: "4px", flexShrink: 0, display: "inline-flex" }}>
                        <FaGithub size={11} />
                      </span>
                      {project.githubUrl}
                    </a>
                  </div>
                )}
                <ul style={{ 
                  listStyleType: "circle", 
                  marginLeft: "18px", 
                  marginTop: "1px",
                  marginBottom: "0",
                  paddingLeft: "0",
                  lineHeight: "1.3"
                }}>
                  {project.achievements.map((achievement, i) => {
                    const colonIndex = achievement.indexOf(':');
                    const hasCategory = colonIndex > 0;
                    const category = hasCategory ? achievement.substring(0, colonIndex).trim() : '';
                    const detail = hasCategory ? achievement.substring(colonIndex + 1).trim() : achievement;
                    
                    return (
                      <li key={i} style={{ 
                        marginTop: "1px", 
                        paddingLeft: "2px",
                        fontSize: "12px",
                        lineHeight: "1.3"
                      }}>
                        {hasCategory ? (
                          <>
                            <span style={{ fontWeight: "bold" }}>{category}:</span> {detail}
                          </>
                        ) : (
                          achievement
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </section>
        )}

        {/* AWARDS */}
        {awards && awards.length > 0 && (
          <section style={{ marginBottom: "8px" }}>
            <SectionHeader children={undefined}>Honors and Awards</SectionHeader>
            {(() => {
              // Group awards by category
              const awardsByCategory: Record<string, Award[]> = {}
              const uncategorized: Award[] = []
              
              awards.forEach(award => {
                const category = award.category?.trim()
                if (category) {
                  if (!awardsByCategory[category]) {
                    awardsByCategory[category] = []
                  }
                  awardsByCategory[category].push(award)
                } else {
                  uncategorized.push(award)
                }
              })
              
              const categories = Object.keys(awardsByCategory).sort()
              
              return (
                <>
                  {categories.map((category, catIndex) => (
                    <div key={category} style={{ 
                      marginBottom: catIndex < categories.length - 1 ? "4px" : "0",
                      fontSize: "12px",
                      lineHeight: "1.3"
                    }}>
                      <span style={{ marginRight: "4px" }}>•</span>
                      <span style={{ fontWeight: 600 }}>{category}:</span>
                      <span> {awardsByCategory[category].map((award, i) => (
                        <span key={i}>
                          {award.name}{i < awardsByCategory[category].length - 1 ? "; " : ""}
                        </span>
                      ))}</span>
                    </div>
                  ))}
                  {uncategorized.length > 0 && (
                    <div style={{ 
                      fontSize: "12px",
                      lineHeight: "1.3"
                    }}>
                      <span style={{ marginRight: "4px" }}>•</span>
                      <span>{uncategorized.map((award, i) => (
                        <span key={i}>
                          {award.name}{i < uncategorized.length - 1 ? "; " : ""}
                        </span>
                      ))}</span>
                    </div>
                  )}
                </>
              )
            })()}
          </section>
        )}

        {/* SKILLS - 分类展示 */}
        <section style={{ marginBottom: "0" }}>
          <SectionHeader children={undefined}>Skills</SectionHeader>
          <div style={{ 
            display: "flex", 
            flexDirection: "column", 
            gap: "6px",
            lineHeight: "1.3"
          }}>
            {/* 原有的技能分类 */}
            {skills.languages && skills.languages.length > 0 && (
              <div style={{ fontSize: "12px" }}>
                <span style={{ fontWeight: 600, marginRight: "6px" }}>Languages:</span>
                <span>{skills.languages.join(", ")}</span>
              </div>
            )}
            {skills.frameworks && skills.frameworks.length > 0 && (
              <div style={{ fontSize: "12px" }}>
                <span style={{ fontWeight: 600, marginRight: "6px" }}>Frameworks:</span>
                <span>{skills.frameworks.join(", ")}</span>
              </div>
            )}
            {skills.technologies && skills.technologies.length > 0 && (
              <div style={{ fontSize: "12px" }}>
                <span style={{ fontWeight: 600, marginRight: "6px" }}>Technologies:</span>
                <span>{skills.technologies.join(", ")}</span>
              </div>
            )}
            {skills.softSkills && skills.softSkills.length > 0 && (
              <div style={{ fontSize: "12px" }}>
                <span style={{ fontWeight: 600, marginRight: "6px" }}>Soft Skills:</span>
                <span>{skills.softSkills.join(", ")}</span>
              </div>
            )}
            {skills.spokenLanguages && skills.spokenLanguages.length > 0 && (
              <div style={{ fontSize: "12px" }}>
                <span style={{ fontWeight: 600, marginRight: "6px" }}>Languages:</span>
                <span>{skills.spokenLanguages.join(", ")}</span>
              </div>
            )}
          </div>
        </section>
      </Page>
    </Document>
  );
}

Resume.documentId = "resume";

export default Resume;
