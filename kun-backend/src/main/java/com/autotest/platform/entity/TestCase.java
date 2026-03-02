package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "test_cases")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TestCase {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(nullable = false, unique = true, length = 50)
    private String caseNumber;

    @Column(name = "tenant_id")
    private Long tenantId;
    
    @Column(nullable = false, length = 200)
    private String title;
    
    @Column(columnDefinition = "TEXT")
    private String description;
    
    @Column(columnDefinition = "TEXT")
    private String preconditions;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private TestType testType = TestType.FUNCTIONAL;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Priority priority = Priority.MEDIUM;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Status status = Status.DRAFT;
    
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_story_id")
    private UserStory userStory;
    
    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "validation_point_id")
    private ValidationPoint validationPoint;
    
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "created_by", nullable = false)
    private User createdBy;
    
    @OneToMany(mappedBy = "testCase", cascade = CascadeType.ALL, orphanRemoval = true, fetch = FetchType.LAZY)
    @Builder.Default
    @OrderBy("stepOrder")
    private List<TestStep> steps = new ArrayList<>();
    
    @OneToOne(mappedBy = "testCase", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    private TestScript testScript;
    
    @OneToMany(mappedBy = "testCase", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    @Builder.Default
    private List<TestExecution> executions = new ArrayList<>();
    
    @Column(length = 255)
    private String tags;
    
    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;
    
    @UpdateTimestamp
    private LocalDateTime updatedAt;
    
    public enum TestType {
        FUNCTIONAL, UI, API, PERFORMANCE, SECURITY, COMPATIBILITY
    }
    
    public enum Priority {
        LOW, MEDIUM, HIGH, CRITICAL
    }
    
    public enum Status {
        DRAFT, REVIEW, READY, DEPRECATED, ARCHIVED
    }
}
