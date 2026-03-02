package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "user_stories")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class UserStory {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(nullable = false, unique = true, length = 50)
    private String usNumber;

    @Column(name = "tenant_id")
    private Long tenantId;
    
    @Column(nullable = false, length = 200)
    private String title;
    
    @Column(columnDefinition = "TEXT")
    private String description;
    
    @Column(columnDefinition = "TEXT")
    private String acceptanceCriteria;

    @Column(columnDefinition = "TEXT")
    private String latestAnalysisPayload;

    private LocalDateTime latestAnalyzedAt;

    @Column(columnDefinition = "TEXT")
    private String latestCaseGenerationPayload;

    private LocalDateTime latestCaseGeneratedAt;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Priority priority = Priority.MEDIUM;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Status status = Status.DRAFT;
    
    @Column(length = 50)
    private String sprint;
    
    @Column(length = 100)
    private String epic;
    
    @Column(length = 50)
    private String storyPoints;
    
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "created_by", nullable = false)
    private User createdBy;
    
    @OneToMany(mappedBy = "userStory", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    @Builder.Default
    private List<TestCase> testCases = new ArrayList<>();
    
    @OneToMany(mappedBy = "userStory", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    @Builder.Default
    private List<ValidationPoint> validationPoints = new ArrayList<>();
    
    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;
    
    @UpdateTimestamp
    private LocalDateTime updatedAt;
    
    public enum Priority {
        LOW, MEDIUM, HIGH, CRITICAL
    }
    
    public enum Status {
        DRAFT, ANALYZING, READY, IN_PROGRESS, PENDING_EXECUTION, DONE, ARCHIVED
    }
}
